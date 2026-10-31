package seat

import (
	"path/filepath"
	"testing"

	"agentkit/internal/harness"
)

// What Python's open takes over and Go does not yet is Python's: a name a gone seat left files
// under, a folder that is a checkout of its own, a harness whose launch writes down more than
// the conversation it hands out.
func TestOpensLeftToPython(t *testing.T) {
	home := sandbox(t)
	state := filepath.Join(home, ".agentkit", "state")
	write(t, filepath.Join(state, "notify-acme.lock"), "") // a lock is no file of the seat's
	if !unclaimed(state, "acme", home) {
		t.Fatal("a name and a folder nothing holds are not Go's")
	}
	write(t, filepath.Join(state, "seat-acme.json"), `{"stopped_at": 1.0, "closed_by_owner": true}`)
	if unclaimed(state, "acme", home) {
		t.Error("Go opens a name a gone seat left its stop mark under")
	}
	write(t, filepath.Join(home, "work", ".git", "HEAD"), "ref: refs/heads/main\n")
	if unclaimed(state, "beta", filepath.Join(home, "work")) {
		t.Error("Go opens a seat in a checkout of its own")
	}
	if _, known := harness.Opens("claude"); !known {
		t.Error("Go does not open a Claude seat")
	}
	if _, known := harness.Opens("codex"); known {
		t.Error("Go opens a Codex seat, whose launch writes down its receipt")
	}
}
