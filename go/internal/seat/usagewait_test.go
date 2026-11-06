package seat

import (
	"path/filepath"
	"testing"
	"time"

	"agentkit/internal/run"
	usages "agentkit/internal/usage"
)

// The refusal is the model's the seat's last answer ran on: where that moved the seat off the
// model its record names, the provider to mark out is the moved one's, which Python moves first.
func TestARefusalIsWaitedOnOnlyForTheModelItsRecordNames(t *testing.T) {
	home := sandbox(t)
	write(t, stateFile(home, "usage.json"), run.Line(run.Fields("fetched_at", seconds(time.Now()),
		"providers", run.Fields("test", run.Fields("meters", []any{})))))
	readings, err := usages.Cached()
	if err != nil {
		t.Fatal(err)
	}
	for _, each := range []struct {
		answered string
		waits    bool
	}{{"", true}, {"opus", true}, {"fable", false}} {
		seat := Seat{Name: "acme", own: "claude", follow: move{chosen: each.answered}}
		live := Live{Name: "acme", Own: "claude", Record: run.Fields("orchestrator", "opus"), File: run.NewObject(),
			State: "at_prompt", Refused: "402 payment required"}
		if _, waits := seat.waitOnUsage(filepath.Join(home, ".agentkit", "state"), live, readings, time.Now(), func(string) {}); waits != each.waits {
			t.Errorf("last answer on %q: waits %v", each.answered, waits)
		}
	}
}
