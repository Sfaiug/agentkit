package launch

import (
	"errors"
	"fmt"
	"io"
	"maps"
	"os"
	"path/filepath"
	"strconv"
	"strings"
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
// max_runs caps, its driver apart, and followed until it ends.  A task whose run merges or passes
// settles, and the job is done once every task delivered.  Any other ending, or a step Python's
// ladder takes before one, it leaves as a launcher that died leaves it, any run kept, for `ak run
// resume <job>`.  A seat's job, one told --bg, one a gate decides and one with a task Go's own
// launch would hand over, whose preflight refuses it or whose pick waits for budget, it leaves to
// Python whole (ErrPython), before anything is written.  `ak run`'s exit status, and why the job
// is refused, "" for one that went on.
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
	for _, l := range tasks {
		if flags["--anyway"] {
			break
		}
		found, err := rivals(l.place.repo, l.path, l.named, l.cmds)
		if err != nil {
			return 0, "", err
		}
		if len(found) > 0 {
			return 2, l.path + ": " + underWayRefusal(found, false), nil
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
	named := filepath.Join(job.Jobs(), time.Now().Format("20060102-150405-")+task.Slug(tasks[0].named))
	j.dir = named
	for n := 2; ; n++ {
		if taken, err := exists(j.dir); err != nil || !taken {
			if err != nil {
				return err
			}
			break
		}
		j.dir = named + "-" + strconv.Itoa(n)
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

// An ending is a task's run as its driver left it.
type ending struct {
	task   *run.Object
	dir    string
	record *run.Object
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
			if left, err := j.begin(task, ended); left != "" || err != nil {
				return j.leave(left), err
			}
			running++
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
			if left, err := j.settle(e); left != "" || err != nil {
				return j.leave(left), err
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
// reads now: a run of its own, its receipt naming the job, filed on the job's before its driver
// starts apart, and followed until it ends.  What leaves the job where Go does not start it.
func (j *jobRun) begin(task *run.Object, ended chan<- ending) (string, error) {
	name := task.Str("name")
	l, _, why, err := j.task(task.Str("task_file"))
	switch {
	case errors.Is(err, ErrPython):
		return name + ": not started", nil
	case err != nil:
		return "", err
	case l == nil:
		return name + ": " + why, nil
	case l.reason != "":
		return name + ": " + l.reason, nil
	case parks(l):
		return name + ": waiting for budget", nil
	}
	run.SetAll(task, "state", "running", "started_at", run.Float(seconds()))
	if err := job.Save(j.dir, j.receipt); err != nil {
		return "", err
	}
	log, unstopped, err := l.make(j.out)
	if err == nil {
		err = prepare(l.dir, l.meta, l.place, l.warning, l.flags, l.seat, unstopped, log)
	}
	if err == nil {
		j.say(name + " start: " + filepath.Base(l.dir))
		task.Set("run_id", filepath.Base(l.dir))
		if err = job.Save(j.dir, j.receipt); err == nil {
			err = start(l.dir, j.out, true)
		}
	}
	if errors.Is(err, ErrStopped) || errors.Is(err, loop.ErrStopped) {
		return name + ": stopped", nil
	}
	if err != nil {
		return "", err
	}
	go func() { ended <- ending{task, l.dir, loop.Await(l.dir, func() {})} }()
	return "", nil
}

// settle is the task's ending, as Python's job_ladder takes up a run that merged or passed: the
// task keeps who built and reviewed it, and its word and line.  What leaves the job for any other.
func (j *jobRun) settle(e ending) (string, error) {
	name, word := e.task.Str("name"), classify(e.record)
	if !run.Ended(e.record) || word != "merged" && word != "passed" {
		state := "gone"
		if e.record != nil {
			state = run.Text(e.record.Get("state"))
		}
		return fmt.Sprintf("%s: %s %s", name, filepath.Base(e.dir), state), nil
	}
	for _, role := range []string{"executor", "reviewer"} {
		if e.record.Truthy(role) {
			e.task.Set(role, e.record.Get(role))
		}
	}
	merged := "not merged"
	if e.record.Truthy("merged") {
		merged = "merged"
	}
	j.say(fmt.Sprintf("%s exit 0: %s %s %s %s", name, filepath.Base(e.dir), run.Text(e.record.Get("state")),
		run.Text(e.record.Get("verdict")), merged))
	run.SetAll(e.task, "state", word, "finished_at", run.Float(seconds()), "verdict_line", verdictLine(name, word, e.record))
	if err := job.Save(j.dir, j.receipt); err != nil {
		return "", err
	}
	j.say(e.task.Str("verdict_line"))
	return "", nil
}

// leave ends this launcher as one that died leaves its job, every run it started going on as it
// goes, for `ak run resume`, whose ladder takes up what this one does not; the exit status.
func (j *jobRun) leave(what string) int {
	if what != "" {
		j.say(what)
		j.say(fmt.Sprintf("job %s: this launcher ends here; ak run resume %s to continue, ak run stop %s to end it", j.id(), j.id(), j.id()))
	}
	return 1
}

// classify is a finished run's word for its task, Python's job_classify: merged, passed where no
// merge was asked, the task is scratch, or its target already had the work or is none, else
// stopped, blocked or failed.
func classify(record *run.Object) string {
	if record == nil {
		return "failed"
	}
	switch state := record.Str("state"); {
	case state == "stopped" || state == "blocked":
		return state
	case state == "not_needed":
		return "passed"
	case record.Truthy("merged"):
		return "merged"
	case !run.ReviewPass(record, run.Models()):
		return "failed"
	case record.Truthy("no_merge") || record.Truthy("scratch") || record.Truthy("on_target"),
		record.Truthy("target") && strings.ToLower(run.Text(record.Get("target"))) == "none":
		return "passed"
	}
	return "failed"
}

// verdictLine is a delivered task's line, Python's job_verdict_line: its rounds, and the pull
// request a merge went through.
func verdictLine(name, word string, record *run.Object) string {
	tail := ""
	if pr := run.Text(record.Get("pr")); word == "merged" && record.Truthy("pr") && strings.HasPrefix(pr, "http") {
		tail = " " + pr
	}
	line := fmt.Sprintf("%s: PASS, %s after %d rounds%s", name, word, len(record.List("round_summaries")), tail)
	return strings.ReplaceAll(line, " after 0 rounds", "")
}
