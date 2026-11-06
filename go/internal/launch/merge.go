package launch

import (
	"io"
	"path/filepath"

	"agentkit/internal/box"
	"agentkit/internal/config"
	"agentkit/internal/helper"
	"agentkit/internal/loop"
	"agentkit/internal/run"
	"agentkit/internal/task"
)

// Merge is `ak run merge <id>` past the refusals its record makes (loop.MergeRefused), Python's
// cmd_merge: its refusals in its words, `ak run`'s exit status, and why it refused.  A run or a
// host Go does not deliver on is Python's (ErrPython), decided before anything is written.
func Merge(id string, out, errOut io.Writer) (int, string, error) {
	dir := filepath.Join(run.Runs(), id)
	record, _ := run.Read(dir)
	if record == nil || elsewhere(id) || !loop.Mergeable(record) || config.Check() != nil || box.Check() != nil || helper.May() {
		return 0, "", ErrPython
	}
	// a delivery from integration checks the task's own commands once more
	if _, _, err := task.Read(filepath.Join(dir, "task.md")); err != nil || !driverHere() {
		return 0, "", ErrPython
	}
	if !run.Carries(record) {
		return 0, "", ErrPython // review off lands on its checks, and only Python delivers that yet
	}
	if !run.ReviewPass(record, run.Models()) {
		return 2, id + ": merge requires a successful reviewer allowed by the model policy; run ak run resume " + id + " to obtain review", nil
	}
	return loop.Merge(dir, out, errOut)
}
