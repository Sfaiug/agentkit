package tick

import (
	"errors"
	"io"

	"agentkit/internal/host"
	"agentkit/internal/run"
)

// reapable is whether Python's reap of that live record is one Go carries: a running loop that is
// gone, with no unit to ask whether its memory cap ended it, or to stop, no worktree for the dead
// loops row to continue into, so its death is the seat's news, which the endings row offers
// (handback.notify_recovery), and no wait, whose landing line Python's save of its ending times
// into history.db and wakes.
func reapable(record *run.Object, now float64) bool {
	return record.Str("state") == "running" && !run.GoesOn(record, now) && !scoped(record) && !directory(record.Str("worktree")) &&
		record.Get("waiting_on") == nil && !run.Lined(record)
}

// interrupted is the record as that reap leaves it (transitions.interrupt).
func interrupted(record *run.Object, now float64) *run.Object {
	return run.SetAll(record, "state", "interrupted", "interrupted_at", now,
		"interruption_reason", "Run process exited or its identity changed.", "recovery_pending", true)
}

// reap writes that reap of the run at dir while it is still the record read, what the dead loop
// left running ended first (turns.stop_run_tree); a run moved on since is Python's.
func reap(dir string, read *run.Object, now float64) error {
	err := run.Change(dir, func(current *run.Object) error {
		if !run.Equal(current, read) {
			return errMovedRun
		}
		host.EndMarked(dir, io.Discard)
		interrupted(current, now)
		return nil
	})
	if errors.Is(err, errMovedRun) {
		return errLeft
	}
	return err
}
