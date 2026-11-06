package cli

import (
	"io"

	"agentkit/internal/tick"
)

func init() { commands["watch"] = watch }

// watch carries out a tick, or a dry run, of a home with nothing to act on, and a tick that finds
// another holding the lock; every other tick comes in a later milestone.
func watch(args []string, out, errOut io.Writer) int {
	if len(args) == 0 && tick.Carry(out, errOut, auditScoreboard(out)) || len(args) > 0 && tick.Dry(out) {
		return 0
	}
	return notImplemented(errOut, "watch")
}
