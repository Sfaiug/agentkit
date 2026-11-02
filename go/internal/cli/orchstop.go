package cli

import (
	"errors"
	"fmt"
	"io"
	"os/signal"
	"syscall"
	"time"

	"agentkit/internal/seat"
)

func init() { commands["orch stop"] = orchStop }

// orchStop stops a seat Go knows as Python's orch.cmd_stop does.  Stopping the seat this runs in
// hangs this very process up halfway through, so the hangup is ignored across all that follows.
func orchStop(args []string, out, errOut io.Writer) int {
	signal.Ignore(syscall.SIGHUP)
	said, known, err := seat.Stop(args[0], time.Now())
	var refused seat.Refusal
	switch {
	case !known:
		return notImplemented(errOut, "orch stop")
	case errors.As(err, &refused):
		fmt.Fprintf(errOut, "ak orch: %s\n", refused)
		return 2
	case err != nil:
		fmt.Fprintf(errOut, "ak orch: %v\n", err)
		return 1
	}
	if said != "" {
		fmt.Fprintln(out, said)
	}
	return 0
}
