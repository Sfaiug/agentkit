package seat

import (
	"testing"

	"agentkit/internal/run"
)

// A seat nobody is in has no harness whose login it could ask about, but gh's and a dead token's
// are every seat's news.
func TestASeatNobodyIsInReadsTheLoginsEverySeatNeeds(t *testing.T) {
	for name, each := range map[string]struct{ watch, word, reason string }{
		"its harness's login refused": {`{"auth_out": {"claude": {"ok": false, "at": 1}}}`, "idle", closedOne},
		"gh logged out":               {`{"gh_out": {"at": 1}}`, "needs you", "GitHub is logged out: run `gh auth login -p https -w`"},
		"a worker token dead": {`{"worker_tokens": {"claude": {"harness": "claude", "remedy": "replace it", "expired": true, "at": 1}}}`,
			"needs you", "claude worker token expired: replace it"},
	} {
		t.Run(name, func(t *testing.T) {
			home := sandbox(t)
			record(t, home, "acme", nil)
			write(t, stateFile(home, "watch.json"), each.watch)
			read, known := Read(moment)
			if !known || len(read.Seats) != 1 || read.Seats[0].Word != each.word || read.Seats[0].reason != each.reason {
				t.Fatalf("%v %+v", known, read.Seats)
			}
		})
	}
}

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
