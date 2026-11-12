package seat

import (
	"strings"
	"time"

	"agentkit/internal/tmux"
)

// The pane may die after its first listing. Read death again after the capture so
// its dead-pane banner never becomes a screen an interrupted turn is inferred from:
// in the same call, whose last line it is, as tmux runs no command after one that failed.
func captureHarness(target string) (string, bool) {
	said, err := tmux.Ask(tmux.Own(), "capture-pane", "-p", "-e", "-J", "-t", target, ";", "display-message", "-p", "-t", target, "#{pane_dead}")
	if err != nil {
		return said, false
	}
	at := strings.LastIndexByte(said, '\n')
	if said[at+1:] == "1" {
		return "", true
	}
	return strings.TrimSpace(said[:max(at, 0)]), false
}

// A look can find the harness dead after listing it live. Its empty capture must
// not replace its last screen with rule=none: revival would invent a cut-off turn.
// Only the error it can no longer be retrying is cleared (watch.live_state).
func (seat Seat) keepExited(state string, found sight) (sight, error) {
	found.stall, found.login = nil, nil
	return found, writeSeat(state, seat.Name, []field{{"stall", nil}, {"login", nil}})
}

// A death discovered after listing is still a gone seat the health row carries.
// Publish it without reading its screen; revival reads it later.
func (home Home) healthDied(state, name string, now time.Time) (bool, error) {
	for at := range home.Seats {
		seat := &home.Seats[at]
		if seat.Name != name {
			continue
		}
		seat.live, seat.held = false, true
		if _, err := seat.keepExited(state, sight{}); err != nil {
			return false, err
		}
		if err := seat.goneAt(state, at+1, now); err != nil {
			return false, err
		}
		return home.healthGone(state, name, now)
	}
	return false, nil
}
