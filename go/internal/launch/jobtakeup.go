package launch

import (
	"cmp"
	"errors"
	"fmt"
	"io"
	"io/fs"
	"path/filepath"
	"slices"

	"agentkit/internal/config"
	"agentkit/internal/job"
	"agentkit/internal/loop"
	"agentkit/internal/run"
)

// jobPickerInterval is how long a job waits before it looks again at a task whose run goes on
// elsewhere, Python's JOB_PICKER_INTERVAL: the one pace every wait of a job keeps (retry_after).
const jobPickerInterval = 60

// endedElsewhere are the states of a run another process ended while a job adopted it, whose
// ending is then the task's (job_adopt_worker).
var endedElsewhere = []string{"pass", "fail", "blocked", "stopped", "not_needed"}

// holds is whether ResumeJob relaunches the dead job on the runs its tasks hold from before,
// which its scheduler takes up (takeUp): a job Go relaunches (relaunched), its runs' options kept
// (adopt), with a task left that runs or holds a run, and none from before `after:` went, waiting
// for the budget Python's picker reads, rerun by Python's ladder, or holding a run whose record Go
// cannot read or that waits on a login, which stay Python's.
func holds(receipt *run.Object) bool {
	if !relaunched(receipt) || receipt.Dict("opts") == nil {
		return false
	}
	held := false
	for _, each := range receipt.List("tasks") {
		task, ok := each.(*run.Object)
		if !ok {
			return false
		}
		_, named := task.Get("name").(string)
		state, stated := task.Get("state").(string)
		if !named || !stated {
			return false
		}
		if slices.Contains(job.Terminal, state) {
			continue
		}
		if state == "waiting" || task.Truthy("after") || task.Truthy("from_pass") || task.Truthy("budget_wait") || task.Truthy("rerun_attempted") {
			return false
		}
		if id, _ := task.Get("run_id").(string); task.Truthy("run_id") {
			record, err := run.Read(filepath.Join(run.Runs(), id))
			if filepath.Base(id) != id || record == nil && !errors.Is(err, fs.ErrNotExist) || record != nil && record.Str("state") == "waiting_login" {
				return false
			}
		}
		held = held || state == "running" || task.Truthy("run_id")
	}
	return held
}

// takeUp begins the task on the run it holds from before, as Python's run_job_loop adopts it
// (job_adopt_worker), never starting it over while that run may still deliver: a run alive
// under another process, or a dead one its reap leaves inside a grace, is looked at again later;
// an unfinished one is resumed by its own resume, which Go's driver carries on, and its ending,
// as the ending of a run that ended, goes to the job's ladder through ended.  A record that is
// gone queues the task with no run, to start over, as a refusal of the run's own does (refused).
// A run whose resume Go leaves to Python, the same at the slot lock as read, is handed over
// (ErrPython) with nothing written for it, as is a record Go cannot read.  Whether it began.
func (j *jobRun) takeUp(task *run.Object, ended chan<- ending) (bool, error) {
	id := task.Str("run_id")
	dir := filepath.Join(run.Runs(), id)
	read, err := run.Read(dir)
	switch {
	case errors.Is(err, fs.ErrNotExist):
		run.SetAll(task, "state", "queued", "run_id", nil)
		return false, job.Save(j.dir, j.receipt)
	case read == nil:
		return false, ErrPython
	case run.Active(read) && run.ProcessActive(read):
		return false, j.later(task, task.Str("state"))
	case !unfinished(read) && run.Active(read):
		return false, j.later(task, "queued")
	case !unfinished(read):
		toLadder(ended, task, dir, func() *run.Object { return read })
		return true, nil
	}
	_, why, err := resume(id, true, nil, nil, nil, io.Discard, io.Discard)
	if errors.Is(err, ErrPython) {
		// Python's resume refuses a record that changed by its slot lock, whatever it holds: only
		// one unchanged there is Python's to carry on
		slots, unheld := holdSlots()
		if unheld != nil {
			return false, unheld
		}
		same := run.Equal(reread(dir), read)
		slots.Close()
		if same {
			return false, ErrPython
		}
		why, err = loop.ErrChanged.Error(), nil
	}
	switch {
	case err != nil:
		return false, err
	case why != "":
		return j.refused(task, dir, read, why, ended)
	}
	toLadder(ended, task, dir, func() *run.Object { return loop.Await(dir, func() {}) })
	return true, nil
}

// refused is the task whose run's own resume refused it, read again as Python's job_adopt_worker
// reads it: an ending another process gave it meanwhile is the task's; a record changed at all,
// though its state reads as before, keeps the run the task's, looked at again later; only one
// nobody changed is the run's own refusal, the task then queued with no run, to start over.
// Whether it began.
func (j *jobRun) refused(task *run.Object, dir string, read *run.Object, why string, ended chan<- ending) (bool, error) {
	name, current := task.Str("name"), reread(dir)
	state := current.Str("state")
	moved := !run.Equal(current.Get("state"), read.Get("state")) || !run.Equal(current.Get("merged"), read.Get("merged"))
	switch {
	case moved && !run.Active(current) && state != "waiting" && (current.Truthy("merged") || slices.Contains(endedElsewhere, state)):
		j.say(fmt.Sprintf("%s: ended elsewhere while adopted: %s", name, run.Text(current.Get("state"))))
		toLadder(ended, task, dir, func() *run.Object { return current })
		return true, nil
	case !run.Equal(current, read):
		j.say(fmt.Sprintf("%s: taken on elsewhere while adopted: %s", name, run.Text(current.Get("state"))))
		return false, j.later(task, "queued")
	}
	j.say(fmt.Sprintf("%s: resume refused: %s", name, why))
	run.SetAll(task, "state", "queued", "run_id", nil)
	return false, job.Save(j.dir, j.receipt)
}

// later has the job look at the task again an interval on, in state, its run kept.
func (j *jobRun) later(task *run.Object, state string) error {
	run.SetAll(task, "state", state, "retry_after", run.Float(seconds()+jobPickerInterval))
	return job.Save(j.dir, j.receipt)
}

// paced is whether the task waits out its retry_after.
func paced(task *run.Object) bool {
	after, _ := task.Num("retry_after")
	return after > seconds()
}

// unfinished is whether the run from before is one Python's job resumes through the run's own
// resume (job_adopt_worker): a launch waiting for its slot whose process died, a loop that died
// outside the grace its reap keeps (GoesOn), an interrupted, exhausted or stalled run, or one
// needing recovery that has not ended and waits on no login.
func unfinished(record *run.Object) bool {
	switch state := record.Str("state"); state {
	case "queued", "running":
		return state == "queued" && record.Truthy("slot_waiting") && !run.ProcessActive(record) || !run.GoesOn(record, seconds())
	case "interrupted", "exhausted", "stalled":
		return true
	case "waiting_login":
		return false
	}
	return run.LandingLine(record) == "" && run.NeedsRecovery(record) && !run.Ended(record)
}

// toLadder sends the task's run's ending, once record reads it, to the job's ladder (settle), with
// the executor list the run is bound to, Python's run_workers: its record's, else the config's.
func toLadder(ended chan<- ending, task *run.Object, dir string, record func() *run.Object) {
	go func() {
		e := ending{task: task, dir: dir, record: record(), adopted: true}
		if e.record != nil && len(e.record.List("workers")) > 0 {
			e.workers = names(e.record.List("workers"))
		} else if bound, err := config.Bind(); err == nil {
			e.workers = names(bound.Workers)
		}
		ended <- e
	}()
}

// reread is the run's record as it reads now, an empty one where none does, as Python reads it.
func reread(dir string) *run.Object {
	record, _ := run.Read(dir)
	return cmp.Or(record, run.NewObject())
}
