package cli

import (
	"io"

	"agentkit/internal/tick"
)

func init() { commands["watch"] = watch }

// watch carries out a tick, or a dry run, of a home with nothing to act on, and a tick that finds
// another holding the lock; every other tick comes in a later milestone.  A tick that could not
// save watch.json fails, as Python's does.  `--live RUN` follows that run's merge to live.
func watch(args []string, out, errOut io.Writer) int {
	left, failed := "", false
	switch {
	case len(args) == 2: // `--live RUN`, as validate passed it
		left, failed = tick.FollowLive(args[1], out, errOut)
	case len(args) > 0:
		left = tick.Dry(out)
	default:
		left, failed = tick.Carry(out, errOut, auditScoreboard(out))
	}
	if failed {
		return 1
	}
	if left == "" {
		return 0
	}
	return handOver(errOut, "watch", left)
}
