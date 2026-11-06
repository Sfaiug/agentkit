//go:build linux || darwin

package cli

import (
	"io"
	"slices"
	"testing"
	"time"

	"agentkit/internal/terminal"
)

// A key a second before Subscriptions is due to read its cells again leaves the read due then, not
// rereadEvery after the key.
func TestAKeyKeepsTheSubscriptionsRefreshDeadline(t *testing.T) {
	t.Setenv("HOME", t.TempDir()) // the shipped config's subscriptions, so the key moves the light
	keyboard := terminal.NewKeyboard()
	start := time.Date(2026, 11, 6, 12, 0, 0, 0, time.UTC)
	at := start
	// what happens while the page waits after each draw, asked to wake at due
	waits := []func(due time.Time){
		func(due time.Time) { at = due.Add(-time.Second); keyboard.Unread(terminal.Key{Name: "down"}) },
		func(due time.Time) { at = due; keyboard.Wake() },
		func(time.Time) { keyboard.Unread(terminal.Key{Name: "esc"}) },
	}
	var woken []time.Duration
	left := menuSubscriptionsOn(keyboard, terminal.NewPainter(io.Discard), func() time.Time { return at }, func(due time.Time) {
		if len(woken) == len(waits) {
			t.Fatalf("a draw more than the %d expected, woken at %v", len(waits), woken)
		}
		woken = append(woken, due.Sub(start))
		waits[len(woken)-1](due)
	})
	// the read the wake brings sets the next wake rereadEvery after it
	if want := []time.Duration{rereadEvery, rereadEvery, 2 * rereadEvery}; !left || !slices.Equal(woken, want) {
		t.Fatalf("back on c %v, woken at %v; want true, %v", left, woken, want)
	}
}
