package cli

import (
	"io"

	"agentkit/internal/tick"
)

func init() { commands["watch"] = watch }

// watch carries out a tick that finds another holding the lock; every other tick, and a dry
// run, comes in a later milestone.
func watch(args []string, out, errOut io.Writer) int {
	if len(args) == 0 && tick.Overlap(out, errOut) {
		return 0
	}
	return notImplemented(errOut, "watch")
}
