package cli

import (
	"io"

	"agentkit/internal/tick"
)

func init() { commands["watch"] = watch }

// watch carries out a tick that finds another holding the lock, and a dry run of a home with
// nothing to act on; every other tick comes in a later milestone.
func watch(args []string, out, errOut io.Writer) int {
	if len(args) == 0 && tick.Overlap(out, errOut) || len(args) > 0 && tick.Dry(out) {
		return 0
	}
	return notImplemented(errOut, "watch")
}
