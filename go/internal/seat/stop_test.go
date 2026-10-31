package seat

import (
	"errors"
	"io/fs"
	"os"
	"path/filepath"
	"testing"
)

func TestStopsLeftToPython(t *testing.T) {
	for name, build := range map[string]func(t *testing.T, state string){
		"a run still going": func(t *testing.T, state string) {
			runRecord(t, filepath.Dir(filepath.Dir(state)), "r-going", map[string]any{"state": "running"})
		},
		"browser tabs recorded as its own": func(t *testing.T, state string) {
			write(t, filepath.Join(state, "browser-tabs.json"), `{"T1": {"opener": {"session": "acme"}}}`)
		},
		"a card a webhook took": func(t *testing.T, state string) {
			write(t, filepath.Join(state, "card-acme.json"), `{"word": "done", "episode": "e1", "sent": true}`)
		},
		"a question's card, which a webhook may have taken": func(t *testing.T, state string) {
			write(t, filepath.Join(state, "card-acme.json"), `{"word": "needs you", "episode": "e1"}`)
		},
		"a question it asked still unseen": func(t *testing.T, state string) {
			write(t, filepath.Join(state, "notify-acme.json"), `{"kind": "needs", "text": "Which branch?"}`)
		},
	} {
		t.Run(name, func(t *testing.T) {
			home := sandbox(t)
			state := filepath.Join(home, ".agentkit", "state")
			record(t, home, "acme", nil)
			build(t, state)
			if _, known, err := Stop("acme", moment); known || err != nil {
				t.Fatalf("Go stopped it: known=%v err=%v", known, err)
			}
			if _, err := os.Stat(filepath.Join(state, "seat-acme.json")); !errors.Is(err, fs.ErrNotExist) {
				t.Fatalf("the stop mark went in: %v", err)
			}
		})
	}
}

// the same seat with nothing of its own Python ends is Go's to stop
func TestStopClosesARecordTmuxLost(t *testing.T) {
	home := sandbox(t)
	record(t, home, "acme", nil)
	if said, known, err := Stop("acme", moment); said != "stopped acme; its number reopens it" || !known || err != nil {
		t.Fatalf("said=%q known=%v err=%v", said, known, err)
	}
}

// a Codex seat, whose record the first stop reconciles, is removed by the second, and the seat
// beside it still reads
func TestStopTwiceRemovesASeatAndLeavesTheRestReadable(t *testing.T) {
	home := sandbox(t)
	record(t, home, "acme", map[string]any{"orchestrator": "astra", "workers": []string{"astra"}})
	record(t, home, "beta", nil)
	for _, want := range []string{"stopped acme; its number reopens it", "removed acme"} {
		if said, known, err := Stop("acme", moment); said != want || !known || err != nil {
			t.Fatalf("said=%q known=%v err=%v", said, known, err)
		}
	}
	if read, known := Read(moment); !known || len(read.Seats) != 1 || read.Seats[0].Name != "beta" {
		t.Fatalf("known=%v seats=%v", known, read.Seats)
	}
}
