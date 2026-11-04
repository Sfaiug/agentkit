package handback

import (
	"time"

	"agentkit/internal/run"
)

// Owed is Python's owes_ending: stopped deliberately, already told, reported, or retrying
// errors owe no ending. A mark from before this attempt ended has not told this ending.
func Owed(record *run.Object, now time.Time) bool {
	return run.OwesEnding(record, now)
}
