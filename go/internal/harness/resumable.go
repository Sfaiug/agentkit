package harness

import "agentkit/internal/run"

// Resumable is whether the seat owns a conversation it may resume where its harness's own evidence
// says so, not its record (Python's orch.resumable); false for known where the record alone says.
func (reader Reader) Resumable(record *run.Object) (resumable, known bool) {
	if hook := reader.own.resumable; hook != nil {
		return hook(record), true
	}
	return false, false
}
