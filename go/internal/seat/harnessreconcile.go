package seat

import (
	"path/filepath"

	"agentkit/internal/config"
	"agentkit/internal/harness"
	"agentkit/internal/run"
)

// Reconcile writes into every seat's record what its harness reconciles in Go, as Python's
// orch.records does before anything claims a seat resumable: each judged on the record as
// Python's lock holds it, and written only where a field changes. A record it cannot write stays
// as it was, a thread it leaves unbound for the reading that meets it to hand to Python. A config
// that does not load names no harness, as Python's orch.loaded reads it.
func Reconcile() {
	models, _ := config.Models()
	state := filepath.Join(config.Home(), "state")
	for _, path := range config.SeatFiles() {
		name, _ := sessionFile(filepath.Base(path))
		update(state, name, func(record *run.Object) bool {
			fields := harness.Reconcile(models[record.Str("orchestrator")].Harness, record)
			var changes []field
			for _, key := range fields.Keys() {
				changes = append(changes, field{key, fields.Get(key)})
			}
			return set(changes)(record)
		})
	}
}
