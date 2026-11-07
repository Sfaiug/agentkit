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

// What moves while an announce queues for a dead-pane seat's lock, its runs aside, is what it decides
// from, or, where Go does not read what moved, it hands over and leaves the seat's file as it found it.
func TestAQueuedAnnounceDecidesFromTheNewestFacts(t *testing.T) {
	file := func(home, name string) string { return filepath.Join(home, ".agentkit", "state", name) }
	for name, each := range map[string]struct {
		meanwhile    func(t *testing.T, home, pane string)
		word, reason string         // none where it hands over
		ran          map[string]any // a run of its own the reading finds, none where nil
	}{
		"a question recorded": {func(t *testing.T, home, _ string) {
			write(t, file(home, "notify-acme.json"), `{"kind": "needs", "text": "which?", "time": 2}`)
		}, "needs you", closedOne, nil},
		"the owner's stop": {func(t *testing.T, home, _ string) {
			write(t, file(home, "seat-acme.json"), `{"stopped_at": 2, "closed_by_owner": true}`)
		}, "idle", "session closed by the owner: reopen it from past sessions", nil},
		"the owner's stop, a run of its own merged waiting to hand back": {func(t *testing.T, home, _ string) {
			write(t, file(home, "seat-acme.json"), `{"stopped_at": 2, "closed_by_owner": true}`)
		}, "idle", "session closed by the owner: reopen it from past sessions · 1 hand-backs waiting",
			map[string]any{"state": "pass", "merged": true, "finished_at": seconds(time.Now()) - 20000, "handback_pending": true}},
		"put to sleep": {func(t *testing.T, home, _ string) {
			record(t, home, "acme", map[string]any{"asleep": 9, "launched": 3})
		}, "idle", "asleep: press 1 to wake it", nil},
		"its panes running again": {func(t *testing.T, home, pane string) {
			if _, err := tmux.Ask(tmux.Own(), "respawn-pane", "-k", "-t", pane, "sleep 60"); err != nil {
				t.Fatal(err)
			}
			write(t, file(home, "seat-acme.json"), `{"word": "working"}`)
		}, "", "", nil},
		"a question kept back": {func(t *testing.T, home, _ string) {
			write(t, file(home, "seat-acme.json"), `{"word": "needs you", "unasked": ["which?"]}`)
		}, "", "", nil},
	} {
		t.Run(name, func(t *testing.T) {
			home := sandbox(t)
			record(t, home, "acme", nil)
			pane := paneDied(t, "acme")
			if each.ran != nil {
				runRecord(t, home, "merged", each.ran)
			}
			found, before, err := queued(t, home, time.Now(), "idle", func() { each.meanwhile(t, home, pane) })
			if each.word == "" {
				if after, _ := os.ReadFile(file(home, "seat-acme.json")); !errors.Is(err, ErrUnread) || string(after) != string(before) {
					t.Fatalf("%v, the seat's file became %s", err, after)
				}
				return
			}
			if err != nil {
				t.Fatal(err)
			}
			saves(t, home, found, each.word, each.reason)
		})
	}
}

// The runs a queued announce of a dead-pane seat decides on are the ones its reading found, judged
// by the clock read once the lock is taken: Python's caller hands its records down to a ladder that
// reads the time as it climbs.
func TestAQueuedAnnounceJudgesTheReadingsRunsOnTheLocksClock(t *testing.T) {
	for name, each := range map[string]struct {
		waited       time.Duration // how long its announce waits, as the clock of its reading reads
		runs         func(t *testing.T, home string, now time.Time) (meanwhile func())
		word, reason string
	}{
		"a run found finishing, and another starting": {0, func(t *testing.T, home string, now time.Time) func() {
			runRecord(t, home, "fix-api", map[string]any{"state": "running", "started_at": seconds(now)})
			return func() {
				runRecord(t, home, "fix-api", map[string]any{"state": "pass", "finished_at": seconds(now)})
				runRecord(t, home, "add-cli", map[string]any{"state": "running", "started_at": seconds(now)})
			}
		}, "working", "1 running · fix-api"},
		"a retry found aging out of the tick's": {time.Hour, func(t *testing.T, home string, now time.Time) func() {
			// the tick admits an ending for a day, which this one passes while its announce waits;
			// waiting to hand back, it is no owner's look then
			runRecord(t, home, "fix-api", map[string]any{"state": "error", "finished_at": seconds(now) - 86400 - 1800, "error_retry_at": seconds(now),
				"handback_pending": true})
			return func() {}
		}, "idle", closedOne},
	} {
		t.Run(name, func(t *testing.T) {
			home := sandbox(t)
			record(t, home, "acme", nil)
			paneDied(t, "acme")
			now := time.Now()
			found, _, err := queued(t, home, now.Add(-each.waited), "working", each.runs(t, home, now))
			if err != nil {
				t.Fatal(err)
			}
			saves(t, home, found, each.word, each.reason)
		})
	}
}

// queued is the announce of acme's home as a reading at `read` finds it, `first` its word, held on
// the seat's lock while `meanwhile` moves the home: that reading as the announce left it, the seat's
// file as it stood when the lock was let go, and what the announce returned.
func queued(t *testing.T, home string, read time.Time, first string, meanwhile func()) (Home, []byte, error) {
	t.Helper()
	path := filepath.Join(home, ".agentkit", "state", "seat-acme")
	found, known := Looking(read)
	if !known || len(found.Seats) != 1 || found.Seats[0].Word != first {
		t.Fatalf("known=%v: %+v", known, found.Seats)
	}
	held, err := lock.Wait(context.Background(), path+".announce")
	if err != nil {
		t.Fatal(err)
	}
	finished := make(chan error)
	go func() { finished <- found.Announce(time.Now()) }()
	// long enough for an announce that decides first to have decided; a slow one only passes
	time.Sleep(300 * time.Millisecond)
	meanwhile()
	before, _ := os.ReadFile(path + ".json")
	held.Close()
	return found, before, <-finished
}

// saves is whether the announce saved that word and reason, and left its reading printing that word.
func saves(t *testing.T, home string, found Home, word, reason string) {
	t.Helper()
	got, _ := run.ReadJSON(filepath.Join(home, ".agentkit", "state", "seat-acme.json"))
	if got == nil {
		t.Fatal("the seat's file was never written")
	}
	if got.Str("word") != word || got.Str("reason") != reason {
		t.Fatal(run.Line(got))
	}
	if found.Seats[0].Word != word { // the word saved is the one printed
		t.Fatalf("it prints %q", found.Seats[0].Word)
	}
}
