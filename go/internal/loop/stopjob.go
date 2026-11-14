package loop

import (
	"errors"
	"fmt"
	"io"
	"path/filepath"
	"slices"
	"time"

	"agentkit/internal/host"
	"agentkit/internal/job"
	"agentkit/internal/run"
)

// errEnded is a run of the job that had ended by its lock: nothing to stop, nothing to say.
var errEnded = errors.New("the run had ended")

// StopJob is `ak run stop <job>`, Python's stop_job of a seat's or the owner's command: under the
// job's lock its launcher ended and every task left unfinished recorded stopped, the job finished,
// so nothing writes the receipt back; then each run of it still going ended as StopRun ends one, its
// stop line said, and last the job's.  A refusal is an error, in Python's words.
func StopJob(id string, keep bool, out io.Writer) error {
	dir := filepath.Join(job.Jobs(), id)
	release, err := run.Hold(dir)
	if err != nil {
		return err
	}
	receipt, stopped, err := stopLauncher(dir)
	release()
	if err != nil {
		return err
	}
	for _, ran := range runsOf(dir, receipt) {
		record, _ := run.Read(ran)
		if record == nil {
			fmt.Fprintf(out, "%s: cannot read %s; left as it is\n", filepath.Base(ran), filepath.Join(ran, "run.json"))
			continue
		}
		if !stoppable(record) {
			continue
		}
		// whether Go ends it was decided before the receipt was written: a handover past that
		// would leave the stop half made
		state, err := end(ran, keep, run.Why, func(current *run.Object) error {
			if err := checkStopOwner(current); err != nil {
				return err
			}
			switch {
			case current.Str("state") == "stopped":
				return errStop
			case !stoppable(current):
				return errEnded
			}
			return nil
		})
		switch {
		case err == nil || errors.Is(err, errStop):
			fmt.Fprintln(out, stopLine(filepath.Base(ran), state))
		case !errors.Is(err, errEnded):
			return err
		}
	}
	if stopped {
		fmt.Fprintf(out, "%s is already stopped\n", id)
	} else {
		fmt.Fprintf(out, "stopped %s\n", id)
	}
	return nil
}

// stopLauncher is StopJob's part under the job's lock: the launcher's tree ended, since it holds
// the receipt and starts any task still queued, then every unfinished task stopped and the job
// finished.  The receipt as it then stands, and whether a stop had finished it already, which a
// second stop leaves as it is to end what the first left going.  A task it cannot read, a unit
// Python's stop_scope stops and a run of the job Go does not end, read once the launcher is gone,
// are Python's (ErrPython), before anything is written; Python's stop then finds the launcher
// gone, as its own would have left it.
func stopLauncher(dir string) (*run.Object, bool, error) {
	id := filepath.Base(dir)
	receipt, err := job.Read(dir)
	if errors.Is(err, run.ErrLoneSurrogate) {
		return nil, false, ErrPython
	}
	var tasks []any
	listed := false
	if receipt != nil {
		tasks, listed = receipt.Get("tasks").([]any)
	}
	if !listed {
		return nil, false, fmt.Errorf("%s: cannot read %s", id, job.ReceiptPath(id))
	}
	if err := checkStopOwner(run.Fields("launched_session", receipt.Get("seat"))); err != nil {
		return nil, false, err
	}
	if slices.ContainsFunc(tasks, func(task any) bool { _, read := task.(*run.Object); return !read }) {
		return nil, false, ErrPython
	}
	stopped := receipt.Truthy("finished_at")
	if stopped && !slices.ContainsFunc(tasks, func(task any) bool { return task.(*run.Object).Str("state") == "stopped" }) {
		return nil, false, fmt.Errorf("%s is already finished; only unfinished work can be stopped", id)
	}
	if host.UserManager() {
		return nil, false, ErrPython
	}
	if pid, _ := receipt.Int("pid"); run.ProcessActive(receipt) {
		host.EndTree(pid)
	}
	if slices.ContainsFunc(runsOf(dir, receipt), func(ran string) bool {
		record, err := run.Read(ran)
		return errors.Is(err, run.ErrLoneSurrogate) || record != nil && stoppable(record) && !goEnds(ran, record)
	}) {
		return nil, false, ErrPython
	}
	if stopped {
		return receipt, true, nil
	}
	now := run.Float(float64(time.Now().UnixNano()) / 1e9)
	for _, task := range tasks {
		if task := task.(*run.Object); !slices.Contains(job.Terminal, task.Str("state")) {
			run.SetAll(task, "state", "stopped", "finished_at", now, "verdict_line", task.Str("name")+": stopped")
		}
	}
	receipt.Set("finished_at", now)
	return receipt, false, job.Write(dir, receipt)
}

// runsOf is every run of the job at dir, job.job_runs: named on its receipt, or naming the job from
// its first write, before the launcher files it there.
func runsOf(dir string, receipt *run.Object) []string {
	named := map[string]bool{}
	for _, task := range receipt.List("tasks") {
		if task, _ := task.(*run.Object); task != nil && task.Str("run_id") != "" {
			named[task.Str("run_id")] = true
		}
	}
	return slices.DeleteFunc(run.Dirs(), func(ran string) bool {
		record, _ := run.Read(ran)
		return !named[filepath.Base(ran)] && (record == nil || record.Str("job_id") != filepath.Base(dir))
	})
}

// stoppable is whether a stop takes the run, Python's stoppable: unfinished work, or an `error`
// whose hourly retry a stop switches off.
func stoppable(record *run.Object) bool {
	return !run.Ended(record) || record.Str("state") == "error"
}
