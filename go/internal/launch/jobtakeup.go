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

// raced is what ResumeJob decides, before anything is written, of each run its job holds whose
// resume Go leaves to Python (ErrPython): Python's resume refuses one changed by its slot lock
// (still), which the job's scheduler then takes up as that refusal (takeUp), so only a job holding
// one unchanged there is Python's, whole.  The runs that changed, by task, as they read before.
func raced(receipt *run.Object) (map[*run.Object]*run.Object, error) {
	changed := map[*run.Object]*run.Object{}
	for _, each := range receipt.List("tasks") {
		task := each.(*run.Object)
		if slices.Contains(job.Terminal, task.Str("state")) || !task.Truthy("run_id") {
			continue
		}
		dir := filepath.Join(run.Runs(), task.Str("run_id"))
		if read, _ := run.Read(dir); read != nil && !(run.Active(read) && run.ProcessActive(read)) && unfinished(read) {
			if _, _, _, err := take(task.Str("run_id"), nil, nil, false); !errors.Is(err, ErrPython) {
				continue
			}
			if same, err := still(dir, read); err != nil || same {
				return nil, cmp.Or(err, ErrPython)
			}
			changed[task] = read
		}
	}
	return changed, nil
}

// takeUp begins the task on the run it holds from before, as Python's run_job_loop adopts it
// (job_adopt_worker), never starting it over while that run may still deliver: a run alive
// under another process, or a dead one its reap leaves inside a grace, is looked at again later;
// an unfinished one is resumed by its own resume, which Go's driver carries on, apart from the
// scheduler (resumed), and its ending, as the ending of a run that ended, goes to the job's ladder
// through ended.  A record that is gone queues the task with no run, to start over; one Go cannot
// read leaves the job, Python's to relaunch (holds).  A run ResumeJob saw change at the slot lock
// is taken up as its resume's refusal (raced).  Whether it began.
func (j *jobRun) takeUp(task *run.Object, ended chan<- ending) (bool, error) {
	dir := filepath.Join(run.Runs(), task.Str("run_id"))
	if read := j.changed[task]; read != nil {
		delete(j.changed, task)
		go func() { ended <- j.refused(task, dir, read, loop.ErrChanged.Error()) }()
		return true, nil
	}
	read, err := run.Read(dir)
	switch {
	case errors.Is(err, fs.ErrNotExist):
		run.SetAll(task, "state", "queued", "run_id", nil)
		return false, job.Save(j.dir, j.receipt)
	case read == nil:
		return false, nil
	case run.Active(read) && run.ProcessActive(read):
		return false, j.later(task, task.Str("state"))
	case !unfinished(read) && run.Active(read):
		return false, j.later(task, "queued")
	case !unfinished(read):
		go func() { ended <- j.adopted(task, dir, read) }()
		return true, nil
	}
	go func() { ended <- j.resumed(task, dir, read) }()
	return true, nil
}

// resumed is the task's run from before carried on by its own resume, its driver followed until
// it ends.  Python's resume refuses a record that changed by its slot lock, whatever it holds, so
// one Go leaves to Python is Python's to carry on only where unchanged there, which leaves the job
// to `ak run resume <job>`, Python's then (raced).
func (j *jobRun) resumed(task *run.Object, dir string, read *run.Object) ending {
	_, why, err := resume(filepath.Base(dir), true, nil, nil, nil, io.Discard, io.Discard)
	if errors.Is(err, ErrPython) {
		var same bool
		if same, err = still(dir, read); err == nil && !same {
			why = loop.ErrChanged.Error()
		}
		if same {
			return ending{task: task, dir: dir, then: func() (bool, error) { return false, nil }}
		}
	}
	switch {
	case err != nil:
		return ending{task: task, dir: dir, then: func() (bool, error) { return false, err }}
	case why != "":
		return j.refused(task, dir, read, why)
	}
	return j.adopted(task, dir, loop.Await(dir, func() {}))
}

// refused is the task whose run's own resume refused it, read again as Python's job_adopt_worker
// reads it: an ending another process gave it meanwhile is the task's; a record changed at all,
// though its state reads as before, keeps the run the task's, looked at again later; only one
// nobody changed is the run's own refusal, the task then queued with no run, to start over.
func (j *jobRun) refused(task *run.Object, dir string, read *run.Object, why string) ending {
	current := reread(dir)
	state := current.Str("state")
	moved := !run.Equal(current.Get("state"), read.Get("state")) || !run.Equal(current.Get("merged"), read.Get("merged"))
	said := func(what string) { j.say(fmt.Sprintf("%s: %s", task.Str("name"), what)) }
	switch {
	case moved && !run.Active(current) && state != "waiting" && (current.Truthy("merged") || slices.Contains(endedElsewhere, state)):
		return ending{task: task, dir: dir, then: func() (bool, error) {
			said("ended elsewhere while adopted: " + run.Text(current.Get("state")))
			return j.adopted(task, dir, current).then()
		}}
	case !run.Equal(current, read):
		return ending{task: task, dir: dir, then: func() (bool, error) {
			said("taken on elsewhere while adopted: " + run.Text(current.Get("state")))
			return true, j.later(task, "queued")
		}}
	}
	return ending{task: task, dir: dir, then: func() (bool, error) {
		said("resume refused: " + why)
		run.SetAll(task, "state", "queued", "run_id", nil)
		return true, job.Save(j.dir, j.receipt)
	}}
}

// adopted is the ending of the task's run from before as record reads it, which goes to the job's
// ladder (settle) with the executor list the run is bound to, Python's run_workers: its record's,
// else the config's; one still under way is looked at again later, as job_adopt_worker does.
func (j *jobRun) adopted(task *run.Object, dir string, record *run.Object) ending {
	return ending{task: task, dir: dir, then: func() (bool, error) {
		if record != nil && run.Active(record) {
			return true, j.later(task, "queued")
		}
		e := ending{task: task, dir: dir, record: record}
		if record != nil && len(record.List("workers")) > 0 {
			e.workers = names(record.List("workers"))
		} else if bound, err := config.Bind(); err == nil {
			e.workers = names(bound.Workers)
		}
		return j.settle(e)
	}}
}

// still is whether the run's record reads at the slot lock as read: Python's resume, which reads
// it there, refuses one that changed (loop.ErrChanged).
func still(dir string, read *run.Object) (bool, error) {
	slots, err := holdSlots()
	if err != nil {
		return false, err
	}
	defer slots.Close()
	return run.Equal(reread(dir), read), nil
}

// later has the job look at the task again an interval on, in state, its run kept.
func (j *jobRun) later(task *run.Object, state string) error {
	run.SetAll(task, "state", state, "retry_after", run.Float(seconds()+jobPickerInterval))
	return job.Save(j.dir, j.receipt)
}

// busy is how many of the job's tasks run, those this launcher carries and those running
// elsewhere, which Python's job counts against --parallel before it starts a queued one.
func busy(tasks []any, running map[*run.Object]bool) int {
	count := 0
	for _, each := range tasks {
		if task := each.(*run.Object); running[task] || task.Str("state") == "running" {
			count++
		}
	}
	return count
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

// reread is the run's record as it reads now, an empty one where none does, as Python reads it.
func reread(dir string) *run.Object {
	record, _ := run.Read(dir)
	return cmp.Or(record, run.NewObject())
}
