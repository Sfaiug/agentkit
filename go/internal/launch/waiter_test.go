//go:build linux

package launch

import (
	"math"
	"os"
	"path/filepath"
	"testing"

	"agentkit/internal/run"
)

// A waiter wakes at its place's share of each poll, as Python's waiter.offset puts it, and a whole
// poll on where the line does not list it.
func TestAWaiterPollsAtItsPlacesShareOfEachPoll(t *testing.T) {
	gatedHome(t, "")
	if err := os.MkdirAll(run.Runs(), 0o777); err != nil {
		t.Fatal(err)
	}
	line := `{"at": 0, "running": 1, "queue": ["a", "b", "c"], "since": 0, "took": [], "last_in": 0}`
	if err := os.WriteFile(filepath.Join(run.Runs(), ".slots.queue"), []byte(line), 0o666); err != nil {
		t.Fatal(err)
	}
	for place, id := range []string{"a", "b", "c"} {
		asked := now()
		wait := untilTurn(id, 3).Seconds()
		// it wakes `place` seconds into each poll of 3 on the clock, give or take the ask's own time
		if late := math.Mod(asked+wait-float64(place)+1.5, 3) - 1.5; wait <= 0 || wait > 3 || math.Abs(late) > 0.1 {
			t.Errorf("%s waits %.3fs, waking %.3fs from its moment", id, wait, late)
		}
	}
	if wait := untilTurn("gone", 3).Seconds(); wait != 3 {
		t.Errorf("a run the line does not list waits %.3fs", wait)
	}
}
