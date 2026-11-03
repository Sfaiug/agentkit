package cli

import (
	"errors"
	"fmt"
	"io"

	"agentkit/internal/gc"
)

func init() {
	commands["run gc"] = runGC
}

// runGC is `ak run gc --dry-run`, its arguments checked already: the collector's plan, changing
// nothing.  The collection itself is Python's.
func runGC(args []string, out, errOut io.Writer) int {
	if len(args) == 0 {
		return notImplemented(errOut, "run")
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
