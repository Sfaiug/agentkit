package seat

import (
	"context"
	"path/filepath"
	"testing"
	"time"

	"agentkit/internal/lock"
	"agentkit/internal/run"
)

// A question recorded while an announce queues for a dead-pane seat's lock is what it decides from.
func TestAQueuedAnnounceDecidesFromTheNewestFacts(t *testing.T) {
	home := sandbox(t)
	record(t, home, "acme", nil)
	paneDied(t, "acme")
	state := filepath.Join(home, ".agentkit", "state")
	found, known := Looking(time.Now())
	if !known || len(found.Seats) != 1 || found.Seats[0].Word != "idle" {
		t.Fatalf("known=%v: %+v", known, found.Seats)
	}
	held, err := lock.Wait(context.Background(), filepath.Join(state, "seat-acme.announce"))
	if err != nil {
		t.Fatal(err)
	}
	finished := make(chan error)
	go func() { finished <- found.Announce(time.Now()) }()
	// long enough for an announce that decides first to have decided; a slow one only passes
	time.Sleep(300 * time.Millisecond)
	write(t, filepath.Join(state, "notify-acme.json"), `{"kind": "needs", "text": "which?", "time": 2}`)
	held.Close()
	if err := <-finished; err != nil {
		t.Fatal(err)
	}
	got, _ := run.ReadJSON(filepath.Join(state, "seat-acme.json"))
	if got == nil {
		t.Fatal("the seat's file was never written")
	}
	if got.Str("word") != "needs you" || got.Str("reason") != closedOne {
		t.Fatal(run.Line(got))
	}
	if found.Seats[0].Word != "needs you" { // the word saved is the one printed
		t.Fatalf("it prints %q", found.Seats[0].Word)
	}
}
