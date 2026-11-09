//go:build linux

package launch

import (
	"fmt"
	"os"
	"path/filepath"
	"testing"

	"agentkit/internal/run"
)

// A first let in on a stall adds nothing to the waits the next stall is judged by: counted, each
// one let in would raise the next one's bar.  One the gates let in adds its wait.
func TestAStallsWaitIsNoPace(t *testing.T) {
	gatedHome(t, "dry-run")
	if err := os.MkdirAll(run.Runs(), 0o777); err != nil {
		t.Fatal(err)
	}
	for stall, want := range map[string]int{"went in on a stall, past: waiting for memory": 3, "": 4} {
		at := now()
		queue := fmt.Sprintf(`{"at": %f, "running": 0, "queue": ["first"], "since": %f, "took": [60.0, 60.0, 60.0]}`, at, at-7200)
		if err := os.WriteFile(filepath.Join(run.Runs(), ".slots.queue"), []byte(queue), 0o666); err != nil {
			t.Fatal(err)
		}
		let := run.Fields("run_id", "first")
		if stall != "" {
			let.Set("slot_stall", stall)
		}
		if err := saveLine(1, nil, nil, let); err != nil {
			t.Fatal(err)
		}
		if saved, _ := queued(); len(saved.took) != want {
			t.Fatalf("let in with slot_stall %q: took %v", stall, saved.took)
		}
	}
}
