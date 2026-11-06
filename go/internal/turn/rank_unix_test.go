//go:build unix

package turn

import (
	"os"
	"testing"

	"agentkit/internal/run"
)

// A line's own check waiting goes before a round's, and before a line's check whose member joined
// later, each seen by the file and lock Python's waiters read.
func TestALinesCheckGoesFirst(t *testing.T) {
	t.Setenv("HOME", t.TempDir())
	if err := os.MkdirAll(run.Runs(), 0o777); err != nil {
		t.Fatal(err)
	}
	round := &Hold{id: "fix-1", since: 1}
	late := &Hold{ask: Ask{Line: true}, id: "fix-3", landing: true, since: 30}
	if round.before() || late.before() {
		t.Fatal("a waiter ranked before them with none waiting")
	}
	early := &Hold{ask: Ask{Line: true}, id: "fix-2", landing: true, since: 20}
	unseen := early.seen()
	if !round.before() {
		t.Error("a round check went before a line's")
	}
	if !late.before() {
		t.Error("a later member's check went before an earlier one's")
	}
	if early.before() {
		t.Error("a line's check ranked behind itself")
	}
	unseen()
	if round.before() || late.before() {
		t.Error("a check that stopped waiting still ranked first")
	}
}
