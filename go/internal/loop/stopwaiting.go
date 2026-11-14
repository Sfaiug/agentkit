package loop

import (
	"agentkit/internal/history"
	"agentkit/internal/run"
)

// historyHolds is whether history.db leaves the run's stop to Python (history.Carried).  Of a run
// waiting for its slot the stop writes only the row, which Finish ends as Python's does, its wait
// counted by the process that waits, if at all: it is held only where that write is Python's.
func historyHolds(id string, record *run.Object) bool {
	if record.Str("state") == "queued" && record.Truthy("slot_waiting") {
		return history.Owed()
	}
	return history.Carried(id)
}
