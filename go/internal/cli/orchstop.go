package cli

import (
	"errors"
	"fmt"
	"io"
	"os"
	"time"

	"agentkit/internal/seat"
)

func init() { commands["orch stop"] = orchStop }

// orchStop stops a seat Go knows as Python's orch.cmd_stop does; a stop run inside a seat is
// Python's, which may stop the very seat it runs in.
func orchStop(args []string, out, errOut io.Writer) int {
	if os.Getenv("AGENTKIT_SESSION") != "" {
		return notImplemented(errOut, "orch stop")
	}
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
	fmt.Fprintln(out, said)
	return 0
}
