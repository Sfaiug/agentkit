package handin

import (
	"errors"
	"os/exec"
	"strings"
	"time"

	"agentkit/internal/run"
)

// checksPass refuses a builder's done while a check of the task's own still fails, as Python's
// failed_checks of the turn's `commands`.  beside is where its output is spooled, outside the
// checkout.
func (t *turn) checksPass(beside string) error {
	var named [][2]string
	if t.checks != nil {
		for _, each := range t.checks.List("commands") {
			command, ok := each.(string)
			if !ok {
				return ErrPython
			}
			named = append(named, [2]string{"$ " + command, command})
		}
	}
	failed, err := t.failedChecks(named, beside)
	if err != nil || len(failed) == 0 {
		return err
	}
	return errors.New("done refused: task checks still fail:\n" + strings.Join(failed, "\n") +
		"\nFix the cause or hand in `ak hand-in blocked \"why\"`.")
}

// failedChecks is how each named command still fails, Python's failed_checks: one after another in
// the checkout, inside one deadline for them all and each with its own silence, the turn's limits
// or else Python's defaults, and each under `timeout`, which tells the worker's watch how long the
// turn may wait on it in silence.  None runs on a host without `timeout`, as in Python.
func (t *turn) failedChecks(named [][2]string, beside string) ([]string, error) {
	timeout, err := exec.LookPath("timeout")
	if err != nil || len(named) == 0 {
		return nil, nil
	}
	workspace, ok := t.workspace.(string)
	if !ok {
		return nil, ErrPython
	}
	bound := func(key string, seconds float64) time.Duration {
		if t.checks != nil {
			if value, ok := t.checks.Num(key); ok {
				seconds = value
			}
		}
		return time.Duration(seconds * float64(time.Second))
	}
	deadline, silence := time.Now().Add(bound("limit", run.CeilingHours*3600)), bound("silence", run.SilenceMinutes*60)
	var failed []string
	for _, each := range named {
		left := time.Until(deadline)
		if left <= 0 {
			break
		}
		said, err := stillFails(timeout, each[1], workspace, beside, left, silence)
		if err != nil {
			return nil, err
		}
		if said != "" {
			failed = append(failed, each[0]+" "+said)
		}
	}
	return failed, nil
}
