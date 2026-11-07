package cli

import (
	"errors"
	"fmt"
	"io"

	"agentkit/internal/gc"
	"agentkit/internal/handover"
	"agentkit/internal/host"
)

func init() {
	commands["run gc"] = runGC
}

// runGC is `ak run gc`, its arguments checked already: the collection, or with `--dry-run` its
// plan, changing nothing.
func runGC(args []string, out, errOut io.Writer) int {
	if len(args) == 0 {
		if errors.Is(gc.Collect(out), gc.ErrPython) {
			return notImplemented(errOut, "run")
		}
		return 0
	}
	plan, err := gc.DryRun()
	if errors.Is(err, gc.ErrPython) {
		return notImplemented(errOut, "run")
	}
	for _, item := range plan {
		fmt.Fprintln(out, item.Line())
	}
	if len(plan) == 0 {
		fmt.Fprintln(out, "gc: no eligible artifacts")
	}
	return 0
}

// collect is `ak gc-collect`, the collection the tick starts to outlive it: 3 where it is Python's.
func collect() int {
	host.Mark("background cleanup")
	if errors.Is(gc.Automatic(), gc.ErrPython) {
		return handover.Exit(handover.Here(0))
	}
	return 0
}
