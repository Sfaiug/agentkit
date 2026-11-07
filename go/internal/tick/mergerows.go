package tick

import (
	"cmp"
	"errors"
	"os/exec"

	"agentkit/internal/history"
	"agentkit/internal/run"
)

// mergeRows is where history.db keeps a followed merge, as Python's after_merge_health does: its
// probe's checks row on the merge commit, under its run's directory.  None on a home without a
// history, which only a suite's lacks: Go's tick makes none, as Python's first write would, since
// one made would leave the rest of the tick to Python.  errLeft where Go cannot write the history
// as it stands, which Python's first write repairs.
func mergeRows(each *merge) (*history.Checked, error) {
	switch {
	case run.Historyless():
		return nil, nil
	case !history.Writable():
		return nil, errLeft
	}
	return &history.Checked{Run: each.name, Kind: "health", Tree: each.sha}, nil
}

// keepMerge is the history.update_run of after_merge_health and live_passed where the merge's
// rows are kept: its run's row keeps the merge commit, and, once it passed, when it went live.
func keepMerge(rows *history.Checked, record *run.Object, passed bool, say func(string)) {
	if rows == nil {
		return
	}
	var live any
	if passed {
		live = record.Get("live_at")
	}
	history.Followed(cmp.Or(record.Str("run_id"), rows.Run), rows.Tree, live, say)
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
