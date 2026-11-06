package harness

import "agentkit/internal/run"

// codexOwned is the thread the seat's launch receipt proves its own, "" for none (codex.py
// `conversation`).
func codexOwned(record map[string]any) string {
	thread, _ := codexThread(run.Fields(codexLaunch, record[codexLaunch], "id_source", record["id_source"], "conversation", record["conversation"]))
	return thread
}

// codexReconciled is what codex.py `reconcile` writes into a seat's record: resumable only where
// its launch's receipt proves a thread, which it then binds; a legacy id stays for diagnosis.
// False where the record holds all of it already.
func codexReconciled(record *run.Object) bool {
	thread, _ := codexThread(record)
	fields := []any{"resumable", thread != ""}
	if thread != "" {
		fields = append(fields, "conversation", thread, "id_source", codexSource)
	}
	changed := false
	for i := 0; i < len(fields); i += 2 {
		if key := fields[i].(string); !run.Equal(record.Get(key), fields[i+1]) || !record.Has(key) {
			record.Set(key, fields[i+1])
			changed = true
		}
	}
	return changed
}
