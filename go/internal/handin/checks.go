package handin

import (
	"errors"
	"strings"
)

// checksPass refuses a builder's done while a check of the task's own still fails, as Python's
// failed_checks of the turn's `commands`: each runs again in the checkout under a worker's limits,
// as a fixer's proofs do.  beside is where its output is spooled, outside the checkout.
func (t *turn) checksPass(beside string) error {
	if t.checks == nil {
		return nil
	}
	var failed []string
	for _, each := range t.checks.List("commands") {
		command, ok := each.(string)
		workspace, known := t.workspace.(string)
		if !ok || !known {
			return ErrPython
		}
		said, err := stillFails(command, workspace, beside)
		if err != nil {
			return err
		}
		if said != "" {
			failed = append(failed, "$ "+command+" "+said)
		}
	}
	if len(failed) == 0 {
		return nil
	}
	return errors.New("done refused: task checks still fail:\n" + strings.Join(failed, "\n") +
		"\nFix the cause or hand in `ak hand-in blocked \"why\"`.")
}
