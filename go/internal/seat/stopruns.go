package seat

import (
	"errors"
	"path/filepath"
	"time"

	"agentkit/internal/job"
	"agentkit/internal/run"
)

// ownRuns is what a stop of the seat finds of the runs it launched: every one's id, for the tabs
// they opened, and the directories of those still going, which the stop takes with it (Python's
// transitions.seat_runs); false where the stop is Python's, for a run it can read and Go cannot,
// a job's, one going that takes more than its record (run.Alone), an error or a parked run whose
// stop turns on what Go does not follow, or a finished one whose checkout goes with the seat
// (stop.release_session).
func ownRuns(name string) (ids, going []string, known bool) {
	for _, dir := range run.Dirs() {
		record, err := run.Read(dir)
		if errors.Is(err, run.ErrLoneSurrogate) {
			return nil, nil, false
		}
		if record == nil || run.Seat(record) != name {
			continue
		}
		id := filepath.Base(dir)
		ids = append(ids, id)
		switch {
		case !run.Ended(record):
			if !run.Alone(dir, record) || exists(job.ReceiptPath(id)) {
				return nil, nil, false
			}
			going = append(going, dir)
		case record.Str("state") == "error", record.Has("lease_wait"), record.Truthy("worktree"):
			return nil, nil, false
		}
	}
	return ids, going, true
}

// stopRuns stops each run, as Python's stop.stop_owned_runs: the lines they say, one that refuses
// named and left, since the seat has ended.
func stopRuns(going []string, now time.Time) []string {
	var said []string
	for _, dir := range going {
		if err := run.Stop(dir, now); err != nil {
			said = append(said, "could not stop "+filepath.Base(dir)+": "+err.Error())
			continue
		}
		said = append(said, "stopped "+filepath.Base(dir))
	}
	return said
}
