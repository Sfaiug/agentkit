package seat

import (
	"context"
	"errors"
	"os"
	"path/filepath"
	"testing"
	"time"

	"agentkit/internal/lock"
	"agentkit/internal/run"
	"agentkit/internal/tmux"
)

// What moves while an announce queues for a dead-pane seat's lock is what it decides from, or, where
// Go does not read what moved, it hands over and leaves the seat's file as it found it.
func TestAQueuedAnnounceDecidesFromTheNewestFacts(t *testing.T) {
	file := func(home, name string) string { return filepath.Join(home, ".agentkit", "state", name) }
	for name, each := range map[string]struct {
		meanwhile    func(t *testing.T, home, pane string)
		word, reason string // none where it hands over
	}{
		"a question recorded": {func(t *testing.T, home, _ string) {
			write(t, file(home, "notify-acme.json"), `{"kind": "needs", "text": "which?", "time": 2}`)
		}, "needs you", closedOne},
		"the owner's stop": {func(t *testing.T, home, _ string) {
			write(t, file(home, "seat-acme.json"), `{"stopped_at": 2, "closed_by_owner": true}`)
		}, "idle", "session closed by the owner: reopen it from past sessions"},
		"the owner's stop, a run of its own merged since waiting to hand back": {func(t *testing.T, home, _ string) {
			write(t, file(home, "seat-acme.json"), `{"stopped_at": 2, "closed_by_owner": true}`)
			runRecord(t, home, "merged", map[string]any{"state": "pass", "merged": true, "finished_at": seconds(time.Now()) - 20000, "handback_pending": true})
		}, "idle", "session closed by the owner: reopen it from past sessions · 1 hand-backs waiting"},
		"put to sleep": {func(t *testing.T, home, _ string) {
			record(t, home, "acme", map[string]any{"asleep": 9, "launched": 3})
		}, "idle", "asleep: press 1 to wake it"},
		"its panes running again": {func(t *testing.T, home, pane string) {
			if _, err := tmux.Ask(tmux.Own(), "respawn-pane", "-k", "-t", pane, "sleep 60"); err != nil {
				t.Fatal(err)
			}
			write(t, file(home, "seat-acme.json"), `{"word": "working"}`)
		}, "", ""},
		"a question kept back": {func(t *testing.T, home, _ string) {
			write(t, file(home, "seat-acme.json"), `{"word": "needs you", "unasked": ["which?"]}`)
		}, "", ""},
	} {
		t.Run(name, func(t *testing.T) {
			home := sandbox(t)
			record(t, home, "acme", nil)
			pane := paneDied(t, "acme")
			found, known := Looking(time.Now())
			if !known || len(found.Seats) != 1 || found.Seats[0].Word != "idle" {
				t.Fatalf("known=%v: %+v", known, found.Seats)
			}
			held, err := lock.Wait(context.Background(), file(home, "seat-acme.announce"))
			if err != nil {
				t.Fatal(err)
			}
			finished := make(chan error)
			go func() { finished <- found.Announce(time.Now()) }()
			// long enough for an announce that decides first to have decided; a slow one only passes
			time.Sleep(300 * time.Millisecond)
			each.meanwhile(t, home, pane)
			before, _ := os.ReadFile(file(home, "seat-acme.json"))
			held.Close()
			err = <-finished
			if each.word == "" {
				if after, _ := os.ReadFile(file(home, "seat-acme.json")); !errors.Is(err, ErrUnread) || string(after) != string(before) {
					t.Fatalf("%v, the seat's file became %s", err, after)
				}
				return
			}
			if err != nil {
				t.Fatal(err)
			}
			got, _ := run.ReadJSON(file(home, "seat-acme.json"))
			if got == nil {
				t.Fatal("the seat's file was never written")
			}
			if got.Str("word") != each.word || got.Str("reason") != each.reason {
				t.Fatal(run.Line(got))
			}
			if found.Seats[0].Word != each.word { // the word saved is the one printed
				t.Fatalf("it prints %q", found.Seats[0].Word)
			}
		})
	}
}
