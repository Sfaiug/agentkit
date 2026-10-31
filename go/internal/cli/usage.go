package cli

import (
	"errors"
	"fmt"
	"io"

	"agentkit/internal/pick"
	"agentkit/internal/run"
	"agentkit/internal/usage"
)

func init() { commands["usage"] = usageJSON }

// usageJSON answers `ak usage --json` as Python's usage.main does: every provider's reading,
// the pick order and the review pair.  The table without --json, and a home whose read or pick
// is Python's, are left to Python before anything is locked or asked.
func usageJSON(args []string, out, errOut io.Writer) int {
	rules, ok := pick.Load()
	if len(args) == 0 || !ok {
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
	order := []any{}
	for _, name := range rules.Order(readings, false) {
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
