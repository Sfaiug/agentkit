package cli

import (
	"errors"
	"fmt"
	"io"

	"agentkit/internal/pick"
	"agentkit/internal/run"
	"agentkit/internal/terminal"
	"agentkit/internal/usage"
)

func init() { commands["usage"] = usageAnswer }

// usageAnswer answers `ak usage` as Python's usage.main does: every provider's reading, the pick
// order and the review pair, as JSON with --json, else drawn (usageText).  A home whose read or
// pick is Python's is left to Python before anything is locked or asked.
func usageAnswer(args []string, out, errOut io.Writer) int {
	rules, ok := pick.Load()
	if !ok {
		return notImplemented(errOut, "usage")
	}
	readings, err := usage.Read()
	if errors.Is(err, usage.ErrPython) {
		return notImplemented(errOut, "usage")
	}
	if err != nil {
		fmt.Fprintf(errOut, "ak usage: %s\n", err)
		return 1
	}
	if len(args) == 0 {
		fmt.Fprintln(out, usageText(terminal.For(out), readings, rules, rules.Order(readings, false, errOut)))
		return 0
	}
	order := []any{}
	for _, name := range rules.Order(readings, false, nil) {
		order = append(order, name)
	}
	answer := run.NewObject()
	answer.Set("providers", readings.Shown())
	answer.Set("pick_order", order)
	answer.Set("review", nil)
	if executor, reviewer, ok := rules.Pair(readings); ok {
		pair := run.NewObject()
		pair.Set("executor", executor)
		pair.Set("reviewer", reviewer)
		pair.Set("self_reviewed", rules.Same(executor, reviewer))
		answer.Set("review", pair)
	}
	fmt.Fprintln(out, run.Encode(answer))
	return 0
}
