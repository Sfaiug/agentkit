package seat

import (
	"testing"

	"agentkit/internal/run"
)

// A replaced token file still dead is a new episode, which begins the word again; an older one
// continues it.
func TestADeadTokensNewEpisodeBeginsItsWordAgain(t *testing.T) {
	home := sandbox(t)
	write(t, stateFile(home, "watch.json"), `{"worker_tokens": {"claude": {"harness": "claude", "remedy": "replace it", "expired": true, "at": 5}}}`)
	dead := "claude worker token expired: replace it"
	for _, each := range []struct {
		reason      string
		since, want float64
	}{{dead, 3, 5}, {"which?", 3, 3}, {dead, 7, 7}} {
		previous := run.NewObject()
		previous.Set("word", "needs you")
		previous.Set("word_since", each.since)
		if got, _ := run.Num(begun(previous, "needs you", each.reason, run.Number("5"), moment)); got != each.want {
			t.Errorf("%q since %v began at %v", each.reason, each.since, got)
		}
	}
}
