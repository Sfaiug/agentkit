package launch

import (
	"errors"
	"fmt"
	"io"
	"maps"
	"os"
	"path/filepath"
	"strconv"
	"time"

	"agentkit/internal/config"
	"agentkit/internal/job"
	"agentkit/internal/loop"
	"agentkit/internal/pick"
	"agentkit/internal/run"
	"agentkit/internal/task"
)

// jobTick is how long the launcher waits between passes over its job when no run ends
// (job.JOB_TICK): each pass touches the receipt, the launcher's heartbeat.
const jobTick = 2 * time.Second

// Job launches the task files at the absolute paths as one job, Python's job_create and
// run_job_loop, for a job launched from no seat in the foreground: its receipt with every task
// queued, then each task an ordinary run of its own, started up to --parallel, which a positive
// max_runs caps, its driver apart, and followed until it ends.  A task settles where Python's
// ladder takes its run no further, delivered or not (ladder), or at its start where its file now
// refuses it, it cannot start or a stop ended it; once every task settled the job is done, or ends
// needing you.  A step Python's ladder takes before such an ending it leaves as a launcher that
// died leaves it, any run kept, for `ak run resume <job>`.  A seat's job, one told --bg, one a
// gate decides and one with a task Go's own launch would hand over, whose preflight refuses it or
// whose pick waits for budget, it leaves to Python whole (ErrPython), before anything is written.
// `ak run`'s exit status, and why the job is refused, "" for one that went on.
func Job(paths []string, values map[string]string, flags map[string]bool, out io.Writer) (int, string, error) {
	limit, capped := config.MaxRuns()
	depth, _ := runDepth()
	if os.Getenv("AGENTKIT_SESSION") != "" || flags["--bg"] || gated(depth) || capped != nil {
		return 0, "", ErrPython
	}
	// a run of the job takes the job's options for one run: no --parallel (job_start_task)
	one := maps.Clone(values)
	delete(one, "--parallel")
	j := &jobRun{values: one, flags: flags, out: out}
	var tasks []*launching
	for _, path := range paths {
		l, code, why, err := j.task(path)
		if l == nil {
			return code, why, err
		}
		if l.reason != "" || parks(l) {
			return 0, "", ErrPython
		}
		tasks = append(tasks, l)
	}
	// a change under way is asked of every task once each passed the rest (job_create)
	if !flags["--anyway"] {
		for _, l := range tasks {
			found, err := rivals(l.place.repo, l.path, l.named, l.cmds)
			if err != nil {
				return 0, "", err
			}
			if len(found) > 0 {
				return 2, l.path + ": " + underWayRefusal(found, false), nil
			}
		}
	}
	var asked any // the receipt keeps --parallel as given, None for none
	if value, given := values["--parallel"]; given {
		j.parallel, _ = strconv.Atoi(value)
		asked = j.parallel
	}
	if limit > 0 && (j.parallel == 0 || limit < j.parallel) {
		j.parallel = limit
	}
	if err := j.create(tasks, asked); err != nil {
		return 0, "", err
	}
	j.say(fmt.Sprintf("job %s: %d tasks", j.id(), len(tasks)))
	code, err := j.carry()
	if errors.Is(err, job.ErrStopped) {
		fmt.Fprintf(out, "%s was stopped\n", j.id())
		return 1, "", nil
	}
	return code, "", err
}

// parks is whether the launch's run would end at its pick before any turn, a wait for budget
// Python's job sits out before it starts the task (run_job_loop).
func parks(l *launching) bool {
	rules, _ := pick.Within(names(l.bound.Workers), names(l.bound.Reviewers))
	return loop.Parks(rules, l.values["--exec"])
}

// A jobRun is a job this process launches: its directory and receipt, the options each of its
// runs takes, how many run at once (0 for no cap), and what says a line on its log.
type jobRun struct {
	dir      string
	receipt  *run.Object
	values   map[string]string
	flags    map[string]bool
	parallel int
	out      io.Writer
	say      func(string)
}

func (j *jobRun) id() string { return filepath.Base(j.dir) }

// task is the launch of the job's task file at path as preflight settles it, read as it reads now,
// as judge says.
func (j *jobRun) task(path string) (*launching, int, string, error) {
	l, text, err := typed(path)
	if err != nil {
		return nil, 0, "", err
	}
	l.job = j
	return l.judge(path, text, j.values, j.flags)
}

// create writes the job's directory, log and receipt, every task queued, as Python's job_create
// does, its id the time and the first task's title (job_make_id).
func (j *jobRun) create(tasks []*launching, parallel any) error {
	cwd, err := os.Getwd()
	if err != nil {
		return err
	}
	if err := os.MkdirAll(job.Jobs(), 0o777); err != nil {
		return err
	}
	if j.dir, err = free(filepath.Join(job.Jobs(), time.Now().Format("20060102-150405-")+task.Slug(tasks[0].named))); err != nil {
		return err
	}
	if err := os.Mkdir(j.dir, 0o777); err != nil {
		return err
	}
	if err := os.WriteFile(filepath.Join(j.dir, "log.txt"), nil, 0o666); err != nil {
		return err
	}
	j.say = jobLogger(j.dir, j.out)
	opts := run.NewObject()
	for _, flag := range []string{"--rounds", "--exec", "--review"} {
		var value any
		if given, ok := j.values[flag]; ok {
			value = given
		}
		opts.Set(flag, value)
	}
	for _, flag := range []string{"--no-merge", "--no-worktree", "--anyway", "--first", "--in-order"} {
		opts.Set(flag, j.flags[flag])
	}
	var listed []any
	for _, l := range tasks {
		listed = append(listed, run.Fields("name", filepath.Base(l.path), "title", l.named, "state", "queued",
			"run_id", nil, "executor", nil, "reviewer", nil, "started_at", nil, "finished_at", nil, "task_file", l.path))
	}
	// this process owns the receipt from its first write, so a kill reads as unfinished, not running
	j.receipt = run.Fields("job_id", j.id(), "seat", nil, "started_at", run.Float(seconds()), "finished_at", nil,
		"parallel", parallel, "executor_history", []any{}, "pid", os.Getpid(), "process_identity", loop.Identity(os.Getpid()),
		"cwd", cwd, "opts", opts, "tasks", listed)
	return job.Save(j.dir, j.receipt)
}

// An ending is a task's run as its driver left it, and the workers that run was bound to.
type ending struct {
	task    *run.Object
	dir     string
	record  *run.Object
	workers []string
}

// carry is the job's scheduler, Python's run_job_loop: queued tasks start up to its cap, each
// run's ending settles its task, and the job ends once every task settled; `ak run`'s exit status.
// It touches the receipt on every pass, its heartbeat.
func (j *jobRun) carry() (int, error) {
	ended := make(chan ending)
	running := 0
	for {
		for _, each := range j.receipt.List("tasks") {
			task := each.(*run.Object)
			if task.Str("state") != "queued" {
				continue
			}
			if j.parallel > 0 && running >= j.parallel {
				break
			}
			begun, err := j.begin(task, ended)
			if err != nil || !begun && task.Str("state") == "queued" {
				return j.leave(), err
			}
			if begun {
				running++
			}
		}
		// every task settled: one that does not leaves the job
		if running == 0 {
			break
		}
		now := time.Now()
		os.Chtimes(job.ReceiptPath(j.id()), now, now)
		select {
		case e := <-ended:
			running--
			if settled, err := j.settle(e); !settled || err != nil {
				return j.leave(), err
			}
		case <-time.After(jobTick):
		}
	}
	j.receipt.Set("finished_at", run.Float(seconds()))
	if err := job.Save(j.dir, j.receipt); err != nil {
		return 0, err
	}
	return jobEnded(j.dir, j.receipt, j.say)
}

// begin starts the task as Python's job_start_task does, its file read again and judged as it
// reads now, refusals and round budget too: a run of its own, its receipt naming the job, filed
// on the job's before its driver starts apart, and followed until it ends.  False where it starts
// no run: the task settled, blocked where its file now refuses it, stopped where a stop ended it
// and failed where it cannot start for any other reason, or, saying why, left queued where Go does
// not start it.  The job's own receipt that cannot be written ends this launcher.
func (j *jobRun) begin(task *run.Object, ended chan<- ending) (bool, error) {
	name := task.Str("name")
	l, _, why, err := j.task(task.Str("task_file"))
	refused := ""
	switch {
	case l != nil:
		refused, err = Refusal(l.path, l.meta, l.cmds)
	case why != "":
		err = errors.New(why)
	}
	switch {
	case errors.Is(err, ErrPython):
		j.say(name + ": not started")
		return false, nil
	case err != nil:
	case parks(l): // Python's job waits for budget before it reads the file's refusal
		j.say(name + ": waiting for budget")
		return false, nil
	case refused != "":
		return false, j.end(task, "blocked", "findings", refused, "verdict_line", name+": BLOCKED: "+refused)
	default:
		run.SetAll(task, "state", "running", "started_at", run.Float(seconds()))
		if err := job.Save(j.dir, j.receipt); err != nil {
			return false, err
		}
		if err = j.ready(l); err == nil {
			j.say(name + " start: " + filepath.Base(l.dir))
			task.Set("run_id", filepath.Base(l.dir))
			if err := job.Save(j.dir, j.receipt); err != nil {
				return false, err
			}
			err = start(l.dir, j.out, true)
		}
	}
	switch {
	case errors.Is(err, ErrStopped) || errors.Is(err, loop.ErrStopped):
		return false, j.end(task, "stopped", "verdict_line", name+": stopped")
	case err != nil:
		return false, j.end(task, "failed", "verdict_line", name+": FAIL: needs you ("+err.Error()+")")
	}
	go func() { ended <- ending{task, l.dir, loop.Await(l.dir, func() {}), names(l.bound.Workers)} }()
	return true, nil
}

// settle takes up the task's ending as Python's job_ladder does, its exit line first: the task
// keeps who built and reviewed it, and settles where the ladder takes its run no further.  False
// for any other, which Python's ladder takes up.
func (j *jobRun) settle(e ending) (bool, error) {
	name, id := e.task.Str("name"), filepath.Base(e.dir)
	if e.record == nil {
		j.say(fmt.Sprintf("%s: %s cannot be read", name, id))
		return false, nil
	}
	for _, role := range []string{"executor", "reviewer"} {
		if e.record.Truthy(role) {
			e.task.Set(role, e.record.Get(role))
		}
	}
	word, code, merged := job.Classify(e.record, run.Models()), 1, "not merged"
	if word == "merged" || word == "passed" {
		code = 0
	}
	if e.record.Truthy("merged") {
		merged = "merged"
	}
	j.say(fmt.Sprintf("%s exit %d: %s %s %s %s", name, code, id, run.Text(e.record.Get("state")),
		run.Text(e.record.Get("verdict")), merged))
	settled, kept := ladder(e.task, e.record, word, e.workers)
	if settled == "" {
		return false, nil
	}
	return true, j.end(e.task, settled, kept...)
}

// leave ends this launcher as one that died leaves its job, every run it started going on as it
// goes, for `ak run resume`, whose ladder takes up what this one does not; the exit status.
func (j *jobRun) leave() int {
	j.say(fmt.Sprintf("job %s: this launcher ends here; ak run resume %s to continue, ak run stop %s to end it", j.id(), j.id(), j.id()))
	return 1
}
