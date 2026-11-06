package launch

import (
	"errors"
	"os"

	"agentkit/internal/run"
	"agentkit/internal/task"
)

// Refusal is the sentence for a task file at path that cannot start as written, "" for none,
// Python's launch_refusal: task.Refusal, then a `rounds:` over the budget in force where it works.
// A queued launch's own child, or a launch from a checkout Python finds, Python judges (elsewhere,
// Budget).
func Refusal(path string, meta map[string]string, cmds []string) (string, error) {
	if why := task.Refusal(meta, cmds); why != "" || Queued() {
		return why, nil
	}
	budget, err := Budget(path)
	if errors.Is(err, ErrPython) {
		return "", nil
	}
	if err != nil {
		return "", err
	}
	return task.RoundsOver(meta["rounds"], "task rounds", budget), nil
}

// Queued is whether this process is a queued launch's own child, which holds what its launch read,
// Python's queued: AGENTKIT_RUN_DIR names a receipt still queued, or one this very process holds
// its slot for (a pickup's exec keeps the pid).  Any other variable is inherited from some other
// run, and refuses nothing less; a record Go cannot read as Python does, Python judges.
func Queued() bool {
	dir := os.Getenv("AGENTKIT_RUN_DIR")
	if dir == "" {
		return false
	}
	record, err := run.Read(dir)
	if errors.Is(err, run.ErrLoneSurrogate) {
		return true
	}
	if record == nil {
		return false
	}
	pid, _ := record.Num("pid")
	return record.Str("state") == "queued" ||
		record.Str("state") == "running" && pid == float64(os.Getpid()) && record.Get("slot_waiting") == false
}
