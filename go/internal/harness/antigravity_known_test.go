package harness

import (
	"os"
	"path/filepath"
	"testing"

	"agentkit/internal/run"
)

// A listing reads the status line's report for the conversation the seat's launch learned, which
// its record names only beside that launch.
func TestAnAntigravityReportIsReadForTheLearnedConversation(t *testing.T) {
	home := t.TempDir()
	t.Setenv("HOME", home)
	t.Setenv("USERPROFILE", home)
	report := reportPath("conv-acme")
	if os.MkdirAll(filepath.Dir(report), 0o700) != nil || os.WriteFile(report, []byte(`{"model": "gemini-3", "effort": "high"}`), 0o600) != nil {
		t.Fatal("no report")
	}
	record := run.Fields("antigravity_launch", "token", "antigravity_open", run.Fields("launch", "token", "conversation", "conv-acme"))
	reader, known := For("antigravity").Reconciled("acme", record)
	if model, effort, _, err := reader.Reported(record); !known || model != "gemini-3" || effort != "high" || err != nil {
		t.Fatalf("reported %q at %v (%v), read: %v", model, effort, err, known)
	}
}
