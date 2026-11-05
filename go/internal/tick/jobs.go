package tick

import (
	"context"
	"errors"
	"fmt"
	"io/fs"
	"os"
	"path/filepath"
	"slices"

	"agentkit/internal/handback"
	"agentkit/internal/job"
	"agentkit/internal/lock"
	"agentkit/internal/run"
)

// jobs is each job's directory and its receipt, nil where Python reads none; false where Go cannot
// read one Python can.
func jobs() ([]string, []*run.Object, bool) {
	entries, err := os.ReadDir(job.Jobs())
	if err != nil {
		return nil, nil, errors.Is(err, fs.ErrNotExist)
	}
	var dirs []string
	var receipts []*run.Object
	for _, entry := range entries {
		dir := filepath.Join(job.Jobs(), entry.Name())
		if info, err := os.Stat(dir); err != nil || !info.IsDir() {
			continue
		}
		receipt, err := run.ReadJSON(filepath.Join(dir, "job.json"))
		if errors.Is(err, run.ErrLoneSurrogate) || errors.Is(err, run.ErrLimit) {
			return nil, nil, false
		}
		dirs, receipts = append(dirs, dir), append(receipts, receipt)
	}
	return dirs, receipts, true
}

// noDeadJobs is resume_dead_jobs with nothing to relaunch: no job whose launcher is gone holds a
// task still to do.
func noDeadJobs() bool {
	_, receipts, read := jobs()
	return read && !slices.ContainsFunc(receipts, func(receipt *run.Object) bool {
		return receipt != nil && receipt.List("tasks") != nil && !receipt.Truthy("finished_at") && !run.ProcessActive(receipt) &&
			slices.ContainsFunc(receipt.List("tasks"), func(each any) bool {
				task, ok := each.(*run.Object)
				return !ok || !slices.Contains(job.Terminal, task.Str("state"))
			})
	})
}

// jobHandbacks is deliver_job_handbacks: a finished job's line its seat could not take when the
// job ended goes in at the seat's next quiet prompt, once.  A seat gone is the owner's to be told
// of, which is Python's.
func (t *ticking) jobHandbacks() error {
	dirs, _, read := jobs()
	if !read {
		return errLeft
	}
	for _, dir := range dirs {
		if err := t.jobHandback(dir); err != nil {
			return err
		}
	}
	return nil
}

// jobHandback reads, types and strikes the line off under the job's delivery lock, so two ticks
// overlapping tell it once.
func (t *ticking) jobHandback(dir string) error {
	held, err := lock.Wait(context.Background(), filepath.Join(dir, "delivery.lock"))
	if err != nil {
		return err
	}
	defer held.Close()
	receipt, err := run.ReadJSON(filepath.Join(dir, "job.json"))
	if errors.Is(err, run.ErrLoneSurrogate) || errors.Is(err, run.ErrLimit) {
		return errLeft
	}
	if receipt == nil || !receipt.Truthy("handback_pending") || !receipt.Truthy("seat") {
		return nil
	}
	line, _ := receipt.Get("handback_pending").(string)
	owner, named := receipt.Get("seat").(string)
	if line == "" || !named {
		return errLeft
	}
	switch handback.TellJob(dir, receipt, line, t.log.line) {
	case handback.Sent:
		t.log.line(fmt.Sprintf("handed job %s back to the %s seat", filepath.Base(dir), owner))
	case handback.Busy:
	default:
		return errLeft
	}
	return nil
}
