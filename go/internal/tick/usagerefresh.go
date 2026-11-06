package tick

import (
	"errors"

	"agentkit/internal/usage"
)

// refreshUsage is Python's usage refresh pass: every provider asked at most once in its harness's
// cadence across the host, so with no menu open the tick is what keeps the readings current. A
// home whose usage Python reads is left to it before anything is asked. No row Go carries reads
// what it read: exhausted resume, which does, is Python's, and Python's tick, reading again, finds
// each provider asked within its cadence and answers from the snapshot this one wrote.
func refreshUsage() error {
	err := usage.Refresh()
	if errors.Is(err, usage.ErrPython) {
		return errLeft
	}
	return err
}
