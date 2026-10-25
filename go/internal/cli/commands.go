package cli

import (
	"fmt"
	"io"
)

// commands holds the operations Go carries out, by the command they answer (`run status`);
// each one's file adds itself.  Main calls one with the words after its command, once help
// and argument refusals have had their say.
var commands = map[string]func(args []string, out, errOut io.Writer) int{}

// notImplemented refuses a command, or a case of one, that Go does not carry out yet.
func notImplemented(errOut io.Writer, command string) int {
	fmt.Fprintf(errOut, "ak %s: not implemented in Go yet\n", command)
	return 3
}
