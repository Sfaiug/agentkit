package harness

import "agentkit/internal/run"

// codexReconcile is codex.py `reconcile`: the thread the launch receipt proves becomes the seat's
// conversation, resumable; a record it proves none of keeps its ids for diagnosis, not resumable.
func codexReconcile(record *run.Object) *run.Object {
	thread, _ := codexThread(record)
	if thread == "" {
		return run.Fields("resumable", false)
	}
	return run.Fields("resumable", true, "conversation", thread, "id_source", codexSource)
}
