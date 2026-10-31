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
