package seat

import (
	"path/filepath"
	"time"

	"agentkit/internal/config"
	"agentkit/internal/harness"
	"agentkit/internal/run"
	"agentkit/internal/tmux"
)

const (
	settle = 500 * time.Millisecond // output stopped this long is a screen at rest
	wake   = 5 * time.Second        // the longest the loop sleeps with nothing moving
	reads  = 5 * time.Second        // the longest a read of the pane is waited for
)

// Follow looks at the seat this wrapper runs in whenever its harness's screen starts moving or comes
// to rest (idle-compact.Looks), which is when what a seat does changes, hook or no hook.  It answers
// what the relay tells of each output; outside a named seat's pane that does nothing.  One follower
// reads the pane, so the terminal never waits on tmux, and starts the seat's own look only where the
// reading is news: a harness that redraws once a second costs a capture a redraw, never a look.
// Edges during a look are one more look.
func Follow(own string) func() {
	launched, server, pane, ok := paneOf()
	if !ok {
		return func() {}
	}
	drawn, edge := make(chan struct{}), make(chan struct{}, 1)
	go edges(drawn, edge, time.After)
	go func() {
		for range edge {
			shown, err := tmux.AskWithin(reads, tmux.Default, "-S", server, "capture-pane", "-p", "-e", "-J", "-t", pane)
			if err != nil || !news(launched, own, shown) {
				continue
			}
			if look := startLook(launched, ""); look != nil {
				look.Wait()
			}
		}
	}()
	return func() { drawn <- struct{}{} }
}

// edges tells of the first output after rest and of output stopped for settle, sleeping as after
// does.  Python's wake also sees a harness's exit and a resize; the relay's waits see those as they
// come, so here it only bounds the sleep.
func edges(drawn <-chan struct{}, edge chan<- struct{}, after func(time.Duration) <-chan time.Time) {
	moving := false
	turn := func() {
		moving = !moving
		select {
		case edge <- struct{}{}:
		default:
		}
	}
	for {
		wait := wake
		if moving {
			wait = settle
		}
		select {
		case <-drawn:
			if !moving {
				turn()
			}
		case <-after(wait):
			if moving {
				turn()
			}
		}
	}
}

// news is whether that capture reads otherwise than the seat's published word was decided from,
// whoever published it (watch.unseen), and Go can make the look that would publish it: one it cannot
// would write nothing, on every edge.
func news(launched, own, pane string) bool {
	name, _, err := config.ResolveSession(launched)
	if err != nil || !(Seat{}).looksOn(own) {
		return false
	}
	now := time.Now()
	found, previous := observed(filepath.Join(config.Home(), "state"), name, harness.For(own), pane, seconds(now))
	if run.Equal(previous.Get("word_from"), found.wordFrom()) {
		return false
	}
	_, _, known := liveSeat(name, now, lookRuns, nil)
	return known
}
