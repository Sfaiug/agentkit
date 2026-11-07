package seat

import (
	"os"
	"path/filepath"
	"reflect"
	"testing"
)

func TestAHomeAnUpdateRanInIsStillRead(t *testing.T) {
	home := sandbox(t)
	record(t, home, "acme", nil)
	state := filepath.Join(home, ".agentkit", "state")
	// what agentkit/update.py keeps there, with the files some of it is written through and locked by
	for _, file := range []string{"harness-swaps.json", "harness-swaps.tmp", "live-check-passed", "live-check-passed.tmp",
		"live-check-passed.lock", "fresh-check-passed", "live-check-held", "live-check-held.tmp", "fresh-check-held",
		"upgrade-check-held", "agentkit-said-update", "agentkit-said-watch", "agentkit-install-pending", "harness-latest.json",
		"harness-update-said.json", "harness-update-said.tmp", "harness-gates/claude/handed", "fresh-gate-faults/handed",
		"live-checks/abc1234-1800000000/output"} {
		write(t, filepath.Join(state, file), "")
	}
	found, known := Read(moment)
	if !known {
		t.Fatal("Read does not know a home an update ran in")
	}
	want := []row{{"acme", "no project", "idle", "no runs yet", "opus", "opus", "session closed: press 1 to reopen"}}
	if got := rows(found); !reflect.DeepEqual(got, want) {
		t.Fatalf("rows:\n got %+v\nwant %+v", got, want)
	}
	// each is known as what it is: a folder where one of its files goes is none of them
	if err := os.Remove(filepath.Join(state, "harness-latest.json")); err != nil {
		t.Fatal(err)
	}
	write(t, filepath.Join(state, "harness-latest.json", "x"), "")
	if _, known := Read(moment); known {
		t.Fatal("Read knows a folder where harness-latest.json goes")
	}
}
