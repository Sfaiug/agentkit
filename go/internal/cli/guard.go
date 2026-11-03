package cli

import (
	"fmt"
	"io"
	"slices"

	"agentkit/internal/commandhelp"
	"agentkit/internal/guard"
)

// guardCall answers the shim asking about a seat's own call, `ak guard <tool> <real tool> <argv...>`,
// unlisted as `adapter` and `hook` are: why it is refused, exiting 1, or the arguments to run it
// with as words for its shell, where they are not the ones it gave.  The shim runs the tool, so
// nothing that goes wrong here can keep it from running.
func guardCall(args []string, out io.Writer) int {
	reason, run := guard.Decide(args[0], args[1], args[2:])
	if reason != "" {
		fmt.Fprintln(out, reason)
		return 1
	}
	if !slices.Equal(run, args[2:]) {
		fmt.Fprintln(out, commandhelp.ShellJoin(run))
	}
	return 0
}
