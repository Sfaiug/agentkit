package seat

import (
	"slices"
	"testing"
)

// A seat holds what its harness's last Stop listed, else what its screen last showed running.
func TestASeatHoldsItsStopsListElseWhatItsScreenShowed(t *testing.T) {
	home := sandbox(t)
	if work := holding("acme"); len(work) != 0 {
		t.Fatal(work)
	}
	write(t, stateFile(home, "seat-acme.json"), `{"holds": ["shell"]}`)
	if work := holding("acme"); !slices.Equal(work, []string{"shell"}) {
		t.Fatal(work)
	}
	write(t, stateFile(home, "hook-acme.json"), `{"session": "acme", "event": "Stop", "at": 1, "holds": ["monitor", "subagent"]}`)
	if work := holding("acme"); !slices.Equal(work, []string{"monitor", "subagent"}) {
		t.Fatal(work)
	}
}
