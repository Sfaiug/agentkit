package tick

import (
	"cmp"
	"errors"
	"fmt"
	"path/filepath"
	"time"

	"agentkit/internal/config"
	"agentkit/internal/launch"
	"agentkit/internal/loop"
	"agentkit/internal/run"
)

// A retry is what the error retry row does with a run in error, as watch.resume_errored decides it.
type retry int

const (
	unmoved  retry = iota // no retry due, and no stamp to take off
	replaced              // a later merged run did the work: its stamps go, and the wait they kept
	given                 // a person's now: its stamps go, with a WARN saying why
	footed                // a record from before errors were stamped: the ladder starts at its foot
	due                   // resumed, a rung up
)

type errored struct {
	dir    string
	record *run.Object
}

// errorRuns is each run in error, and the index of the runs that may replace one, a smoke run's
// aside; false where a record is one Go cannot read as Python does.
func errorRuns() ([]errored, run.Index, bool) {
	var found []errored
	var records []*run.Object
	ok := run.Every(func(dir string, record *run.Object) bool {
		if !run.SmokeRun(record) {
			records = append(records, record)
		}
		if record.Str("state") == "error" {
			found = append(found, errored{dir, record})
		}
		return true
	})
	return found, run.NewIndex(records), ok
}

// retryOf is what the row does with that run in error now, and why a person's is.
func retryOf(each errored, index run.Index, now time.Time) (retry, string) {
	record := each.record
	stamped := record.Has("error_retry_at") || record.Has("error_retries")
	why := ""
	switch {
	case index.MergedOver(record) && stamped:
		return replaced, ""
	case index.MergedOver(record):
		return unmoved, ""
	case !loop.ErrorResumable(each.dir, record):
		why = "cannot be resumed where it stopped"
	case run.TickAdmission(record, now) == "":
		why = "ending is no longer admitted for automatic retry"
	}
	at, timed := dated(record, "error_retry_at")
	switch {
	case why != "" && stamped:
		return given, why
	case why != "" || timed && epoch(now) < at:
		return unmoved, ""
	case !timed:
		return footed, ""
	}
	return due, ""
}

// A dry row hands over wherever Python's says what it would do: a retry to stamp, one due, or a
// person's run to take stamps off.
func noErrorRetry() bool {
	runs, index, ok := errorRuns()
	for _, each := range runs {
		if move, _ := retryOf(each, index, time.Now()); move != unmoved && move != replaced {
			return false
		}
	}
	return ok
}

// errorRetry is watch.resume_errored: each move written under the record's lock, and a due run
// resumed by Go's own resume, its rung climbed before the driver owns the run, so a start that
// fails is tried again a rung up. A due run Go's resume does not carry is Python's, as it stood.
func (t *ticking) errorRetry() error {
	runs, index, ok := errorRuns()
	if !ok {
		return errLeft
	}
	now := t.clock()
	for _, each := range runs {
		move, why := retryOf(each, index, now)
		id := filepath.Base(each.dir)
		switch move {
		case unmoved:
			continue
		case due:
			if !t.resumeErrored(id, each, now) {
				return errLeft
			}
			continue
		}
		err := run.Change(each.dir, func(current *run.Object) error {
			if !run.Equal(current, each.record) {
				return errMovedRun
			}
			if move == footed {
				loop.ScheduleErrorRetry(current, now)
			} else {
				loop.DropErrorRetry(current)
			}
			return nil
		})
		switch {
		case errors.Is(err, errMovedRun):
			return errLeft
		case err != nil:
			// one record that cannot be written keeps no other run from its retry
			t.log.line(fmt.Sprintf("WARN cannot check run %s: %s", id, config.PyError(err)))
		case move == given:
			t.log.line(fmt.Sprintf("WARN %s: %s; leaving it parked for a person", id, why))
		}
	}
	return nil
}

// resumeErrored resumes a due run a rung up, false where the run is Python's as it stands: one
// Go's resume leaves to it, or one that moved since the tick read it. The climb is the resume's
// order, so a run its resume hands over has none.
func (t *ticking) resumeErrored(id string, each errored, now time.Time) bool {
	var decided *run.Object
	climb := func(current *run.Object) {
		loop.ClimbErrorRetry(current, now)
		decided = current.Copy()
	}
	code, said, err := launch.ResumeExpected(id, each.record, climb, nil)
	switch {
	case errors.Is(err, launch.ErrPython):
		return false
	case err == nil && code == 0:
		t.log.line(fmt.Sprintf("resumed %s: error retry %s", id, run.Field(decided, "error_retries", "None")))
		return true
	}
	t.log.line(fmt.Sprintf("WARN could not resume %s: %s", id, cmp.Or(said, fmt.Sprint(err))))
	// a start that failed before the resume wrote its order climbs here
	moved := run.Change(each.dir, func(current *run.Object) error {
		if !run.Equal(current, each.record) {
			return errMovedRun
		}
		climb(current)
		return nil
	})
	return !errors.Is(moved, errMovedRun)
}
