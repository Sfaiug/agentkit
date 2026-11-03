package handback

import (
	"time"

	"agentkit/internal/run"
)

// Owed is Python's owes_ending: stopped deliberately, already told, reported, or retrying
// errors owe no ending. A mark from before this attempt ended has not told this ending.
func Owed(record *run.Object, now time.Time) bool {
	return record.Str("state") != "stopped" && !(record.Str("state") == "error" && run.Going(record, now)) &&
		run.Ended(record) && !handedBack(record) && !record.Truthy("reported")
}
