package seat

import (
	"testing"
	"time"

	"agentkit/internal/run"
	"agentkit/internal/tmux"
)

func TestAnEdgeIsTheFirstOutputAfterRestAndOutputStopped(t *testing.T) {
	drawn, edge := make(chan struct{}), make(chan struct{}, 1)
	slept, rang := make(chan time.Duration), make(chan time.Time)
	go edges(drawn, edge, func(wait time.Duration) <-chan time.Time {
		slept <- wait
		return rang
	})
	// the loop asleep again for that long, with that many edges told since it last slept
	sleeps := func(wait time.Duration, told int) {
		t.Helper()
		if got := <-slept; got != wait {
			t.Fatalf("slept %s, not %s", got, wait)
		}
		if got := len(edge); got != told {
			t.Fatalf("%d edges, not %d", got, told)
		}
		for range told {
			<-edge
		}
	}
	sleeps(wake, 0)
	rang <- time.Now() // nothing moving: a wake and nothing else
	sleeps(wake, 0)
	for range 2 {
		drawn <- struct{}{} // the first output after rest
		sleeps(settle, 1)
		drawn <- struct{}{} // more of it
		sleeps(settle, 0)
		rang <- time.Now() // stopped
		sleeps(wake, 1)
	}
}

func TestOnlyAReadingOtherThanTheWordsIsNews(t *testing.T) {
	home := sandbox(t)
	record(t, home, "acme", nil)
	drawn(t, home, "acme", spinning)
	if !news("acme", "claude", spinning) {
		t.Fatal("a seat nobody has looked at has news")
	}
	before, _ := run.ReadJSON(stateFile(home, "seat-acme.json"))
	if before != nil {
		t.Fatalf("a reading wrote %v", before)
	}
	explained(t, "acme")
	redrawn := "✻ Moonwalking… (11s · ↓ 208 tokens)\n────────\n❯\n────────\n  ⏵⏵ bypass permissions on (shift+tab to cycle)\n"
	if news("acme", "claude", spinning) || news("acme", "claude", redrawn) {
		t.Fatal("a redraw of the turn the word was decided from is no news")
	}
	if !news("acme", "claude", prompting) {
		t.Fatal("a turn ended is news")
	}
	if news("acme", "no-such-harness", prompting) {
		t.Fatal("a harness Go does not read has no reading to compare")
	}
	write(t, stateFile(home, "watch.json"), `{"stalls": {"acme": {"kind": "login", "at": 1}}}`) // what Go does not read yet
	if news("acme", "claude", prompting) {
		t.Fatal("a look Go cannot make is never started")
	}
}

func TestAWaitedLookPublishesALiveSeatsScreen(t *testing.T) {
	home := sandbox(t)
	record(t, home, "acme", nil)
	show := drawn(t, home, "acme", spinning)
	pane, err := tmux.Ask(tmux.Own(), "display-message", "-p", "-t", "=acme:", "#{pane_id}")
	if err != nil {
		t.Fatal(err)
	}
	looked(t, pane, "acme")
	file, _ := run.ReadJSON(stateFile(home, "seat-acme.json"))
	if file == nil || file.Str("word") != "working" || file.Str("rule") != "working.spinner" {
		t.Fatalf("published %v", file)
	}
	write(t, stateFile(home, "watch.json"), `{"stalls": {"acme": {"kind": "login", "at": 1}}}`) // what Go does not read yet
	show(prompting)
	looked(t, pane, "acme")
	if file, _ = run.ReadJSON(stateFile(home, "seat-acme.json")); file.Str("rule") != "working.spinner" {
		t.Fatalf("a look Go cannot make wrote %v", file)
	}
}
