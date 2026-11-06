package seat

import (
	"path/filepath"
	"testing"
)

func TestARenamedSeatKeepsItsRowAndItsRuns(t *testing.T) {
	home := sandbox(t)
	record(t, home, "acme", map[string]any{"repo": "", "filed": true})
	drawn(t, home, "acme", prompting)
	runRecord(t, home, "going", map[string]any{"state": "running", "project": ""})
	// what a rename keeps under the old name
	for _, file := range []string{"rulebook-acme.md", "handover-acme.md", "plan-acme.md"} {
		write(t, filepath.Join(home, ".agentkit", "state", file), "# Kept\n")
	}
	if said, known, err := Rename("acme", "beta", false, moment); !known || err != nil {
		t.Fatalf("rename: %s known=%v error=%v", said, known, err)
	}
	if after, known := Menu(moment); !known || len(after.Seats) != 1 || after.Seats[0].Name != "beta" || after.Seats[0].Word != "working" {
		t.Fatalf("after rename: known=%v seats=%+v", known, after.Seats)
	}
}
