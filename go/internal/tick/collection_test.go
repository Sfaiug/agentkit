//go:build unix

package tick

import (
	"io"
	"os"
	"path/filepath"
	"testing"
	"time"

	"agentkit/internal/gc"
)

// This test program started as the tick's collector ends at once, so a collection started by
// mistake never runs these tests again.
func init() {
	if len(os.Args) > 1 && os.Args[1] == gc.CollectVerb {
		os.Exit(0)
	}
}

// A due collection whose plan is Python's hands the tick over at its row, before any collector of
// Go's starts: a detached collector's handover would reach nobody.
func TestACollectionPythonPlansHandsTheTickOver(t *testing.T) {
	ak, _ := idleHome(t, answers)
	if err := os.Remove(filepath.Join(ak, "state", "gc.json")); err != nil {
		t.Fatal(err)
	}
	// a seat record Go does not read as Python does, whose cursor is Python's to take out
	put(t, filepath.Join(ak, "state", "session-acme.json"), "{\"name\": \"\xff\"}")
	tick := &ticking{log: newLog(io.Discard, io.Discard), clock: time.Now}
	for _, row := range table(tick) {
		if row.name == "collection" {
			if tick.through([]pass{row}) {
				t.Fatal("the tick carried a collection Python plans")
			}
			return
		}
	}
	t.Fatal("no collection row")
}
