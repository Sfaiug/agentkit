package cli

import (
	"agentkit/internal/history"
	"agentkit/internal/run"
)

// machineRow is a run as `ak run status --json` gives it, Python's {**row, **state, "paths": ...}:
// its history.db row, for its record's run_id, else its folder's name, the record over it, a key
// both hold where the row put it, then its paths.
func machineRow(db *history.DB, entry listed) *run.Object {
	id := entry.record.Get("run_id")
	if !entry.record.Truthy("run_id") {
		id = entry.name()
	}
	row := db.Row(id)
	for _, key := range entry.record.Keys() {
		row.Set(key, entry.record.Get(key))
	}
	row.Set("paths", resultPaths(entry))
	return row
}
