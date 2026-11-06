package harness

import "agentkit/internal/run"

// codexOwned is the thread the seat's launch receipt proves its own, "" for none (codex.py
// `conversation`).
func codexOwned(record map[string]any) string {
	thread, _ := codexThread(run.Fields(codexLaunch, record[codexLaunch], "id_source", record["id_source"], "conversation", record["conversation"]))
	return thread
}
