package tick

import (
	"cmp"
	"errors"
	"fmt"
	"path/filepath"
	"slices"
	"time"

	"agentkit/internal/config"
	"agentkit/internal/launch"
	"agentkit/internal/loop"
	"agentkit/internal/run"
)

// resumeEvery is the least time between two resumes the row starts of one run, Python's
// RESUME_EVERY: one may still be on its way, and one that failed waits that long to try again.
const resumeEvery = 600

// exhaustedResume is watch.resume_exhausted: each run waiting `exhausted` on a provider's window
// goes on by Go's own resume once the pick a resume makes finds a pair with room, handed to
// another executor where its own has none, its order written with the resume taking the run up; a
// run a later merged run replaced is settled, marked `replaced`, and never resumed.  A run waiting
// on a reviewer, or on a refusal's short retry, is Python's.  A dry tick writes and starts
// nothing, and says the resume it would start.
func (t *ticking) exhaustedResume() error {
	var waiting []errored
	var records []*run.Object
	if !run.Every(func(dir string, record *run.Object) bool {
		if !run.SmokeRun(record) {
			records = append(records, record)
		}
		if run.ExhaustedWait(record) != "" {
			waiting = append(waiting, errored{dir, record})
		}
		return true
	}) {
		return errLeft
	}
	index, now := run.NewIndex(records), t.clock()
	for _, each := range waiting {
		if err := t.resumeExhausted(each, index, now); err != nil {
			return err
		}
	}
	return nil
}

// resumeExhausted is the row's move on one run waiting `exhausted`, errLeft where it is Python's.
func (t *ticking) resumeExhausted(each errored, index run.Index, now time.Time) error {
	id, record, at := filepath.Base(each.dir), each.record, epoch(now)
	last, stamped := dated(record, "exhausted_resume_at")
	switch {
	case run.ExhaustedWait(record) != "window" || record.Has("refusal_retry"):
		return errLeft
	case index.MergedOver(record):
		if t.dry {
			return nil
		}
		// a later merged run did the work: the wait nothing will lift ends here
		return t.changeExhausted(id, each, func(current *run.Object) { current.Set("replaced", true) })
	case stamped && 0 <= at-last && at-last < resumeEvery:
		return nil
	case !directory(record.Str("worktree")):
		worktree := cmp.Or(record.Str("worktree"), "(none)")
		if t.dry {
			t.log.line(fmt.Sprintf("would leave %s alone: worktree %s is gone", id, worktree))
			return nil
		}
		if record.Get("exhausted_resume_at") != nil {
			return nil
		}
		// once for the life of the missing worktree: the stamp keeps later ticks silent
		t.log.line(fmt.Sprintf("WARN %s is exhausted but its worktree %s is gone; leaving it for an explicit resume", id, worktree))
		return t.changeExhausted(id, each, func(current *run.Object) { current.Set("exhausted_resume_at", at) })
	}
	executor, reviewer, dry, ok := loop.ResumeModels(record, t.dry)
	if !ok {
		return errLeft
	}
	if dry != "" {
		return nil
	}
	model, err := config.ModelNamed(executor)
	if err != nil {
		return errLeft
	}
	if t.dry {
		t.log.line(fmt.Sprintf("would resume %s: %s window refilled", id, model.Provider))
		return nil
	}
	order := resumeOrder(executor, reviewer, at)
	code, said, err := launch.ResumeExpected(id, record, order, nil)
	switch {
	case errors.Is(err, launch.ErrPython):
		return errLeft
	case err == nil && code == 0:
		t.log.line(fmt.Sprintf("resumed %s: %s window refilled", id, model.Provider))
		return nil
	}
	t.log.line(fmt.Sprintf("WARN could not resume %s: %s", id, cmp.Or(said, fmt.Sprint(err))))
	// a start that failed before the resume wrote its order waits resumeEvery as one that started
	return t.changeExhausted(id, each, order)
}

// resumeOrder is what the row writes on a run it resumes, Python's: the executor it hands the
// work to where its own has no room, the reviewer the pick gave, fresh where it changed, and the
// moment of the resume.
func resumeOrder(executor, reviewer string, at float64) func(*run.Object) {
	return func(record *run.Object) {
		if saved := record.Str("executor"); executor != saved {
			handed := append(slices.Clone(record.List("executor_history")), run.Fields("at", at, "from", saved, "to", executor, "reason", "dry"))
			run.SetAll(record, "executor_history", handed, "executor", executor, "exec_session", nil)
		}
		if reviewer != record.Str("reviewer") {
			// the conversation, and a review attempt left open, are the replaced reviewer's
			run.SetAll(record, "reviewer", reviewer, "review_session", nil)
			if pending := record.Dict("review_pending"); pending != nil {
				pending.Set("handed", true)
			}
		}
		record.Set("exhausted_resume_at", at)
	}
}

// changeExhausted writes the row's move on the run as the row read it; one that moved since is
// Python's, and one that cannot be written keeps no other run from its move.
func (t *ticking) changeExhausted(id string, each errored, move func(*run.Object)) error {
	err := run.Change(each.dir, func(current *run.Object) error {
		if !run.Equal(current, each.record) {
			return errMovedRun
		}
		move(current)
		return nil
	})
	switch {
	case errors.Is(err, errMovedRun):
		return errLeft
	case err != nil:
		t.log.line(fmt.Sprintf("WARN cannot check run %s: %s", id, config.PyError(err)))
	}
	return nil
}
