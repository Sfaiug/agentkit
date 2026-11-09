package harness

import (
	"os"
	"path/filepath"
	"testing"

	"agentkit/internal/config"
	"agentkit/internal/run"
)

// A listing's copy of the record, read before another command claimed the conversation its launch's
// agy holds open, owns that conversation throughout the listing: the seat may resume it, its last
// answer is read from its store, and its status line's report for it; a copy relaunched since owns
// nothing yet.
func TestAnAntigravityListingKeepsTheConversationItsLaunchLearned(t *testing.T) {
	home := t.TempDir()
	t.Setenv("HOME", home)
	t.Setenv("USERPROFILE", home)
	state := filepath.Join(config.Home(), "state")
	claimed := run.Fields("antigravity_launch", "token", "antigravity_open", run.Fields("launch", "token", "conversation", "conv-acme"))
	if os.MkdirAll(state, 0o700) != nil || os.WriteFile(filepath.Join(state, "session-acme.json"), []byte(run.Encode(claimed)+"\n"), 0o600) != nil ||
		os.WriteFile(reportPath("conv-acme"), []byte(`{"model": "gemini-3.8-flash", "effort": "high"}`), 0o600) != nil {
		t.Fatal("no home")
	}
	agyStore(t, antigravityStore("conv-acme"), agyGeneration{"gemini-3.8-flash-high", 200})
	read := run.Fields("antigravity_launch", "token")
	reader, known := For("antigravity").Reconciled("acme", read)
	resumable, _ := reader.Resumable(read)
	answered, _, _, found := reader.LastAnswer(read)
	reported, effort, _, err := reader.Reported(read)
	if !known || !resumable || !found || answered != "gemini-3.8-flash" || reported != "gemini-3.8-flash" || effort != "high" || err != nil {
		t.Fatalf("read %v: resumable %v, answered %v (%v), reported %q at %v (%v)", known, resumable, answered, found, reported, effort, err)
	}
	if resumable, _ := reader.Resumable(run.Fields("antigravity_launch", "later")); resumable {
		t.Fatal("a relaunched seat owns its stale launch's conversation")
	}
}
