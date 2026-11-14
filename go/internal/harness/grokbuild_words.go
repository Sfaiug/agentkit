package harness

import "agentkit/internal/run"

// grokRecord takes a record naming no conversation or one it may resume (grokbuild.py `resumable`),
// which grokbuild.py `reconcile` leaves as it is, and leaves dropping any other to Python.
func grokRecord(_ string, record *run.Object) (plugin, bool) {
	return plugins["grokbuild"], !record.Truthy("conversation") || grokOwns(record, record.Str("conversation"))
}
