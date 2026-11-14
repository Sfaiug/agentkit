package harness

import "agentkit/internal/run"

// codexOwned is the thread the seat's launch receipt proves its own, "" for none (codex.py
// `conversation`).
func codexOwned(record map[string]any) string {
	thread, _ := codexFound(record)
	return thread
}

// codexFound is codexOwned, and the error where that receipt or the rollout proving it is there
// and cannot be read (codexProven).
func codexFound(record map[string]any) (string, error) {
	thread, _, err := codexRollout(record)
	return thread, err
}

// codexRollout is codexFound's thread and the rollout Codex keeps it in.
func codexRollout(record map[string]any) (thread, rollout string, err error) {
	return codexProven(run.Fields(codexLaunch, record[codexLaunch], "id_source", record["id_source"], "conversation", record["conversation"]))
}
