package cli

import (
	"fmt"
	"io"

	"agentkit/internal/config"
	"agentkit/internal/tick"
)

func init() { commands["watch"] = watch }

// watch carries out a tick, or a dry run, of a home with nothing to act on, and a tick that finds
// another holding the lock; every other tick comes in a later milestone.  A tick that could not
// save watch.json fails, as Python's does.
func watch(args []string, out, errOut io.Writer) int {
	if len(args) > 0 {
		if tick.Dry(out) {
			return 0
		}
		return notImplemented(errOut, "watch")
	}
	carried, err := tick.Carry(out, errOut, auditScoreboard(out))
	if err != nil {
		fmt.Fprintf(errOut, "ak watch: %s\n", config.PyError(err))
		return 1
	}
	if carried {
		return 0
	}
	return notImplemented(errOut, "watch")
}
