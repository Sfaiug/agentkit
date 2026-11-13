package launch

import (
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
	"agentkit/internal/host"
	"agentkit/internal/job"
	"agentkit/internal/loop"
	"agentkit/internal/run"
	"agentkit/internal/seat"
)

// jobUndelivered are the task states whose work never landed (job.JOB_UNDELIVERED).
var jobUndelivered = []string{"failed", "blocked", "stopped"}

// ResumeJob is `ak run resume <job>`, Python's cmd_job_resume, for the launcher a `--bg` job
// started apart, which carries it on (adopt) while no task of it started yet, a kept run being
// Python's to adopt (job_adopt_worker), and for a job that ends at once: each task still to
// do is one from a receipt before `after:` went with no run kept, which no fresh run may start, so
// it goes back to its seat blocked (job_legacy_refusal), and the job's line is handed back to the
// seat that launched it, woken where it sleeps.  `ak run`'s exit status; any other job is Python's
// (ErrPython), before anything is written.
func ResumeJob(id string, out io.Writer) (int, error) {
	dir := filepath.Join(job.Jobs(), id)
	release, err := run.Hold(dir)
	if err != nil {
		return 0, err
	}
	receipt, _ := job.Read(dir)
	release()
	if receipt == nil || config.Check() != nil || box.Check() != nil {
		return 0, ErrPython
	}
	if ownChild(dir, receipt) && unstarted(receipt) {
		return adopt(dir, receipt, out)
	}
	if !endsAtOnce(receipt) {
		return 0, ErrPython
	}
	say := jobLogger(dir, out)
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
	if errors.Is(saved, job.ErrStopped) {
		fmt.Fprintf(out, "%s was stopped; nothing to resume\n", id)
		return 1, nil
	}
	if saved != nil {
		return 0, saved
	}
	return jobEnded(dir, receipt, say)
}

// unstarted is whether every task of the job is queued and keeps no run, as the job was created.
func unstarted(receipt *run.Object) bool {
	for _, each := range receipt.List("tasks") {
		if task, ok := each.(*run.Object); !ok || task.Str("state") != "queued" || task.Truthy("run_id") {
			return false
		}
	}
	return true
}

// jobLogger says a line on out and in the job's log, as Python's job_logger does.
func jobLogger(dir string, out io.Writer) func(string) {
	return func(text string) {
		line := time.Now().Format("15:04:05") + " " + text
		fmt.Fprintln(out, line)
		if !loop.Logging(dir) {
			if file, err := os.OpenFile(filepath.Join(dir, "log.txt"), os.O_WRONLY|os.O_APPEND|os.O_CREATE, 0o666); err == nil {
				fmt.Fprintln(file, line)
				file.Close()
			}
		}
	}
}

// jobEnded is the end of Python's run_job_loop for a job every task of which settled: the job
// finished, what its tasks came to said and handed back, and `ak run`'s exit status.
func jobEnded(dir string, receipt *run.Object, say func(string)) (int, error) {
	receipt.Set("finished_at", run.Float(seconds()))
	tasks := receipt.List("tasks")
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
	if line := orderedLine(receipt); line != "" {
		text = line
	}
	accepted, err := handBackJob(dir, receipt, name, text, say)
	if err != nil {
		return 0, err
	}
	if undelivered > 0 || !accepted {
		return 1, nil
	}
	return 0, nil
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
