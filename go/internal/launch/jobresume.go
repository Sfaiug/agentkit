package launch

import (
	"context"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"slices"
	"strings"
	"time"

	"agentkit/internal/box"
	"agentkit/internal/config"
	"agentkit/internal/handback"
	"agentkit/internal/host"
	"agentkit/internal/job"
	"agentkit/internal/lock"
	"agentkit/internal/loop"
	"agentkit/internal/run"
	"agentkit/internal/seat"
)

// jobUndelivered are the task states whose work never landed (job.JOB_UNDELIVERED).
var jobUndelivered = []string{"failed", "blocked", "stopped"}

// ResumeJob is `ak run resume <job>`, Python's cmd_job_resume, for a job that ends at once: each
// task still to do is one from a receipt before `after:` went with no run kept, which no fresh run
// may start, so it goes back to its seat blocked (job_legacy_refusal), and the job's line is handed
// back to the seat that launched it, woken where it sleeps.  `ak run`'s exit status; any other job
// is Python's (ErrPython), before anything is written.
func ResumeJob(id string, out io.Writer) (int, error) {
	dir := filepath.Join(job.Jobs(), id)
	release, err := run.Hold(dir)
	if err != nil {
		return 0, err
	}
	receipt, _ := job.Read(dir)
	release()
	if !endsAtOnce(receipt) || config.Check() != nil || box.Check() != nil {
		return 0, ErrPython
	}
	say := func(text string) {
		line := time.Now().Format("15:04:05") + " " + text
		fmt.Fprintln(out, line)
		if !loop.Logging(dir) {
			if file, err := os.OpenFile(filepath.Join(dir, "log.txt"), os.O_WRONLY|os.O_APPEND|os.O_CREATE, 0o666); err == nil {
				fmt.Fprintln(file, line)
				file.Close()
			}
		}
	}
	tasks := receipt.List("tasks")
	for _, each := range tasks {
		if task := each.(*run.Object); !slices.Contains(job.Terminal, task.Str("state")) {
			task.Set("state", "queued")
		}
	}
	// this process owns the receipt from here on, so a kill reads as unfinished, not running
	run.SetAll(receipt, "pid", os.Getpid(), "process_identity", loop.Identity(os.Getpid()))
	saved := job.Save(dir, receipt)
	for _, each := range tasks {
		if task := each.(*run.Object); saved == nil && task.Str("state") == "queued" {
			why := legacy(task)
			run.SetAll(task, "state", "blocked", "finished_at", run.Float(seconds()), "findings", why,
				"verdict_line", task.Str("name")+": BLOCKED: "+why)
			if saved = job.Save(dir, receipt); saved == nil {
				say(task.Str("verdict_line"))
			}
		}
	}
	if saved == nil {
		receipt.Set("finished_at", run.Float(seconds()))
		saved = job.Save(dir, receipt)
	}
	if errors.Is(saved, job.ErrStopped) {
		fmt.Fprintf(out, "%s was stopped; nothing to resume\n", id)
		return 1, nil
	}
	if saved != nil {
		return 0, saved
	}
	undelivered, stopped, findings, failed := 0, 0, "", []*run.Object{}
	for _, each := range tasks {
		task := each.(*run.Object)
		switch state := task.Str("state"); {
		case state == "stopped":
			undelivered, stopped = undelivered+1, stopped+1
		case slices.Contains(jobUndelivered, state):
			undelivered, failed = undelivered+1, append(failed, task)
			if findings == "" {
				findings = task.Str("findings")
			}
		}
	}
	name := run.Text(receipt.Get("job_id"))
	text := fmt.Sprintf("job %s: all %d tasks finished", name, len(tasks))
	if len(failed) > 0 {
		text = fmt.Sprintf("job %s: %d task(s) need you", name, len(failed))
		if stopped > 0 {
			text += fmt.Sprintf(", %d stopped", stopped)
		}
		if said := []rune(findings); len(said) > 0 {
			text += ": " + string(said[:min(len(said), 200)])
		}
		for _, task := range failed {
			if task.Truthy("findings") {
				say(task.Str("name") + " findings:\n" + task.Str("findings"))
			}
		}
		say("job " + name + ": Needs you")
	} else {
		if stopped > 0 {
			text = fmt.Sprintf("job %s: %d task(s) stopped, nobody is needed", name, stopped)
		}
		say("job " + name + ": Done")
	}
	if err := handBackJob(dir, receipt, name, text, say); err != nil {
		return 0, err
	}
	if undelivered > 0 {
		return 1, nil
	}
	return 0, nil
}

// handBackJob is the end of Python's run_job_loop: the job's line typed into the seat that launched
// it, under the job's delivery lock, else kept on the receipt for the tick to type at its next
// quiet prompt.  A seat that went between the look and the line is the tick's to tell the owner of.
func handBackJob(dir string, receipt *run.Object, name, text string, say func(string)) error {
	line := text + ". Result: " + filepath.Join(dir, "log.txt") + ". Decide the next step."
	held, err := lock.Wait(context.Background(), filepath.Join(dir, "delivery.lock"))
	if err != nil {
		return err
	}
	defer held.Close()
	if !receipt.Truthy("seat") {
		say("no seat launched this job, so nothing is sent; the result is here and in `ak run status`")
		receipt.Set("card_sent", run.Fields("kind", "needs", "at", receipt.Get("finished_at")))
		return job.Save(dir, receipt)
	}
	if handback.TellJob(dir, receipt, line, say) != handback.Sent {
		handback.MarkJob(dir, receipt, "handback_pending", line, "handback_card", text)
		say("job " + name + ": its seat is not at its prompt; the tick hands it back")
	}
	return nil
}

// endsAtOnce is whether the job is one ResumeJob finishes: tasks Go reads, at least one still to
// do and each such a task from before `after:` went with no run kept and no wait to sit out, no
// launcher alive, nothing finished before, no unit of its own to stop, and a seat, if it names
// one, there or asleep to hand its line back to.
func endsAtOnce(receipt *run.Object) bool {
	if receipt == nil || !receipt.Has("job_id") || receipt.Truthy("finished_at") || run.ProcessActive(receipt) {
		return false
	}
	if scope, _ := receipt.Get("scope").(string); receipt.Truthy("scope") && host.UserManager() &&
		(scope == "" || scope != "none" && !strings.HasPrefix(scope, "none (")) {
		return false
	}
	if owner, named := receipt.Get("seat").(string); receipt.Truthy("seat") && (!named || !seat.Asleep(owner) && !seat.Watching(owner)) {
		return false
	}
	tasks, left := receipt.List("tasks"), false
	for _, each := range tasks {
		task, ok := each.(*run.Object)
		if !ok {
			return false
		}
		if _, named := task.Get("name").(string); !named {
			return false
		}
		state, stated := task.Get("state").(string)
		if stated && slices.Contains(job.Terminal, state) {
			continue
		}
		after, _ := run.Num(task.Get("retry_after"))
		if !stated || state == "running" || task.Truthy("run_id") || after > seconds() || legacy(task) == "" ||
			task.Truthy("after") && task.List("after") == nil || task.Truthy("from_pass") && task.Dict("from_pass") == nil {
			return false
		}
		left = true
	}
	return left
}

// legacy is why a task from a receipt before `after:` went cannot get a fresh run, "" for any
// other (job_legacy_refusal).
func legacy(task *run.Object) string {
	deps := task.List("after")
	if from := task.Dict("from_pass"); len(deps) == 0 && from != nil {
		deps = []any{from.Get("task")}
	}
	named := make([]string, len(deps))
	for i, dep := range deps {
		named[i] = run.Text(dep)
	}
	if len(named) == 0 {
		return ""
	}
	return fmt.Sprintf("`after:` is gone; launch %s on its own once %s merged", task.Str("name"), strings.Join(named, ", "))
}

func seconds() float64 { return float64(time.Now().UnixNano()) / 1e9 }
