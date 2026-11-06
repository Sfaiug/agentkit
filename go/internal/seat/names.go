package seat

import (
	"path/filepath"
	"slices"

	"agentkit/internal/config"
)

// Names is what holds a seat's name as tmux says now, read once for a question's every answer.
type Names struct {
	state string
	held  []string
	seats map[string]string
}

// ReadNames asks tmux what it holds, writing nothing.
func ReadNames() Names {
	state := filepath.Join(config.Home(), "state")
	held, seats := holdings(state)
	return Names{state, held, seats}
}

// Seat is whether tmux holds a seat by that name (orch.find).
func (names Names) Seat(name string) bool {
	for held := range names.seats {
		if config.Fold(held) == name {
			return true
		}
	}
	return false
}

// Held is whether ak's tmux server holds a session by that name, a seat or not (orch.held_names).
func (names Names) Held(name string) bool {
	return slices.Contains(names.held, name)
}

// Taken is whether no new seat may have that name, as orch.taken_names reads it; false for known
// where only Python's listing can say.
func (names Names) Taken(name string) (taken, known bool) {
	if _, seat := names.seats[name]; seat || names.Held(name) {
		return true, true
	}
	target, _, err := config.ResolveSession(name)
	if err != nil {
		return false, false
	}
	return claimed(names.state, name, target, names.seats)
}
