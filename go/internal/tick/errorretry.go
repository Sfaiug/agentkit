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
// resumed by Go's own resume once it has climbed its rung, which a resume that never starts keeps.
// A due run Go's resume does not carry is Python's, as it stood.
func (t *ticking) errorRetry() error {
	runs, index, ok := errorRuns()
	if !ok {
		return errLeft
	}
	now := t.clock()
	for _, each := range runs {
		move, why := retryOf(each, index, now)
		if move == unmoved {
			continue
		}
		if move == due && !launch.Carries(each.dir, each.record) {
			return errLeft
		}
		var decided *run.Object
		err := run.Change(each.dir, func(current *run.Object) error {
			if !run.Equal(current, each.record) {
				return errMovedRun
			}
			switch move {
			case replaced, given:
				loop.DropErrorRetry(current)
			case footed:
				loop.ScheduleErrorRetry(current, now)
			case due:
				loop.ClimbErrorRetry(current, now)
			}
			decided = current.Copy()
			return nil
		})
		if errors.Is(err, errMovedRun) {
			return errLeft
		}
		id := filepath.Base(each.dir)
		if err != nil {
			// one record that cannot be written keeps no other run from its retry
			t.log.line(fmt.Sprintf("WARN cannot check run %s: %s", id, config.PyError(err)))
			continue
		}
		switch move {
		case given:
			t.log.line(fmt.Sprintf("WARN %s: %s; leaving it parked for a person", id, why))
		case due:
			if code, said, err := launch.ResumeExpected(id, decided); err != nil || code != 0 {
				t.log.line(fmt.Sprintf("WARN could not resume %s: %s", id, cmp.Or(said, fmt.Sprint(err))))
			} else {
				t.log.line(fmt.Sprintf("resumed %s: error retry %s", id, run.Field(decided, "error_retries", "None")))
			}
		}
	}
	return nil
}
