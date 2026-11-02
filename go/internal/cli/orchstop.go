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
	return orchAnswer("orch stop", said, known, err, out, errOut)
}

// orchAnswer is what a seat's verb answers: Python's where Go does not know, a refusal in its
// words, or what it says once done.
func orchAnswer(verb, said string, known bool, err error, out, errOut io.Writer) int {
	var refused seat.Refusal
	switch {
	case !known:
		return notImplemented(errOut, verb)
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
