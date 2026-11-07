package cli

import (
	"fmt"
	"io"

	"agentkit/internal/handover"
)

// commands holds the operations Go carries out, by the command they answer (`run status`);
// each one's file adds itself.  Main calls one with the words after its command, once help
// and argument refusals have had their say.
var commands = map[string]func(args []string, out, errOut io.Writer) int{}

// notImplemented refuses a command, or a case of one, that Go does not carry out yet, handing it
// over where it is called.
func notImplemented(errOut io.Writer, command string) int {
	return handOver(errOut, command, handover.Here(1))
}

// handOver refuses command, which site leaves to Python.
func handOver(errOut io.Writer, command, site string) int {
	fmt.Fprintf(errOut, "ak %s: not implemented in Go yet\n", command)
	return handover.Exit(command, site)
}
