package tick

import (
	"cmp"
	"errors"
	"os/exec"

	"agentkit/internal/history"
	"agentkit/internal/run"
)

// keepsHistory is whether Go's tick writes history.db, as Python's tick does: not on a home whose
// history is bare (history.Bare), which only a suite's is, since a row written would leave the rest
// of the tick to Python; errLeft, before anything is written, where Go cannot write it as it
// stands, which Python's first write repairs.
func keepsHistory() (bool, error) {
	switch {
	case history.Bare():
		return false, nil
	case !history.Writable():
		return false, errLeft
	}
	return true, nil
}

// mergeRows is where history.db keeps a followed merge, as Python's after_merge_health does: its
// probe's checks row on the merge commit, under its run's directory; none where the tick keeps no
// history, nor in a dry tick, which writes none and never opens history.db: opening it at all
// writes beside it, and the first open compiles SQLite into the user's cache.
func mergeRows(each *merge, dry bool) (*history.Checked, error) {
	if dry {
		return nil, nil
	}
	if keeps, err := keepsHistory(); !keeps {
		return nil, err
	}
	return &history.Checked{Run: each.name, Kind: "health", Tree: each.sha}, nil
}

// keepMerge is the history.update_run of after_merge_health and live_passed where the merge's
// rows are kept: its run's row keeps the merge commit, and, once it passed, when it went live.
func keepMerge(rows *history.Checked, record *run.Object, passed bool, say func(string)) {
	if rows == nil {
		return
	}
	pairs := []any{"merge_sha", rows.Tree}
	if passed {
		pairs = append(pairs, "live_at", record.Get("live_at"))
	}
	history.Update(cmp.Or(record.Str("run_id"), rows.Run), say, pairs...)
}

// probeExit is how a probe ended as its row keeps it: its exit as Python's returncode says it,
// nil where it timed out.
func probeExit(failed error, timedOut bool) *int {
	if timedOut {
		return nil
	}
	code := 0
	if exited := (*exec.ExitError)(nil); errors.As(failed, &exited) {
		code = exitCode(exited)
	}
	return &code
}
