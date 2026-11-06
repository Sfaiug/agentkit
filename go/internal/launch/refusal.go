package launch

import (
	"errors"
	"os"

	"agentkit/internal/task"
)

// Refusal is the sentence for a task file at path that cannot start as written, "" for none,
// Python's launch_refusal: task.Refusal, then a `rounds:` over the budget in force where it works.
// A launch from inside a run, or from a checkout Python finds, Python judges (elsewhere, Budget).
func Refusal(path string, meta map[string]string, cmds []string) (string, error) {
	if why := task.Refusal(meta, cmds); why != "" || os.Getenv("AGENTKIT_RUN_DIR") != "" {
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
