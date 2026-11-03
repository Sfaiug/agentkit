package cli

import (
	"fmt"
	"io"
	"os"
	"syscall"

	"agentkit/internal/guard"
)

// guardCall is what a shim hands a seat's own call to, `ak guard <tool> <real tool> <argv...>`,
// unlisted as `adapter` and `hook` are: a refusal says why and exits 1, and anything else becomes
// the real tool, in the caller's environment and in this process's place.
func guardCall(args []string, errOut io.Writer) int {
	real := args[1]
	reason, run := guard.Decide(args[0], real, args[2:])
	if reason != "" {
		fmt.Fprintln(errOut, reason)
		return 1
	}
	err := syscall.Exec(real, append([]string{real}, run...), os.Environ())
	fmt.Fprintf(errOut, "%s-shim: %v\n", args[0], err)
	return 126
}
