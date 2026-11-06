package seat

import (
	"path/filepath"
	"testing"

	"agentkit/internal/harness"
)

// A gone seat's files remain Python's, and a launch writing down more than Go writes.
func TestOpensLeftToPython(t *testing.T) {
	home := sandbox(t)
	state := filepath.Join(home, ".agentkit", "state")
	write(t, filepath.Join(state, "notify-acme.lock"), "") // a lock is no file of the seat's
	if !unclaimed(state, "acme") {
		t.Fatal("an unclaimed name is not Go's")
	}
	write(t, filepath.Join(state, "seat-acme.json"), `{"stopped_at": 1.0, "closed_by_owner": true}`)
	if unclaimed(state, "acme") {
		t.Error("Go opens a name a gone seat left its stop mark under")
	}
	if _, known := harness.Opens("claude"); !known {
		t.Error("Go does not open a Claude seat")
	}
	if _, known := harness.Opens("codex"); !known {
		t.Error("Go does not open a Codex seat")
	}
	if _, known := harness.Opens("antigravity"); known {
		t.Error("Go opens an Antigravity seat, whose launch writes down more than its id")
	}
	if _, known := harness.Opens("acme"); !known {
		t.Error("a harness only its manifest and adapter name does not open a seat")
	}
}
