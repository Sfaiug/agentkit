package seat

import (
	"path/filepath"
	"testing"

	"agentkit/internal/run"
)

// A replaced token file still dead is a new episode, which begins the word again from the reading
// that found it; an older one continues it, as does any other rung's word.
func TestADeadTokensNewEpisodeBeginsItsWordAgain(t *testing.T) {
	home := sandbox(t)
	write(t, stateFile(home, "watch.json"), `{"worker_tokens": {"claude": {"harness": "claude", "remedy": "replace it", "expired": true, "at": 5}}}`)
	said, err := everySeatsNews(climbing{tick: tickFound(filepath.Dir(stateFile(home, "watch.json")))})
	if err != nil || said == nil || said.reason != "claude worker token expired: replace it" {
		t.Fatalf("a dead token says %+v, %v", said, err)
	}
	for _, each := range []struct {
		anew        bool
		since, want float64
	}{{said.anew, 3, 5}, {false, 3, 3}, {said.anew, 7, 7}} {
		previous := run.NewObject()
		previous.Set("word", "needs you")
		previous.Set("word_since", each.since)
		if got, _ := run.Num(begun(previous, "needs you", said.since, each.anew, moment)); got != each.want {
			t.Errorf("anew %v since %v began at %v", each.anew, each.since, got)
		}
	}
}
