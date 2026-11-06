package seat

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestLaunchHistoryDoesNotExpandStopAdmission(t *testing.T) {
	home := sandbox(t)
	t.Setenv("PATH", t.TempDir())
	t.Setenv("AGENTKIT_SESSION", "")
	record(t, home, "acme", map[string]any{
		"orchestrator": "fable", "codex_launch": strings.Repeat("a", 32),
		"codex_history": []any{map[string]any{"conversation": "conv-before-acme", "id_source": "launcher", "receipt": map[string]any{}}},
	})
	path := filepath.Join(home, ".agentkit", "state", "session-acme.json")
	before := contents(t, path)
	// A move keeps the previous harness's evidence beside the current one's.
	// Drawing the record requires no cleanup of that evidence; stopping may.
	if home, known := Read(moment); !known || len(home.Seats) != 1 || home.Seats[0].Orchestrator != "fable" {
		t.Fatalf("cannot read a moved seat: known=%v, seats=%v", known, home.Seats)
	}
	if _, known, err := Stop("acme", moment); known || err != nil {
		t.Fatalf("stopped a seat with unported harness evidence: known=%v, err=%v", known, err)
	}
	if contents(t, path) != before {
		t.Fatal("handoff changed the record")
	}
	if _, err := os.Stat(seatFile("acme")); !os.IsNotExist(err) {
		t.Fatalf("handoff left a stop mark: %v", err)
	}
}
