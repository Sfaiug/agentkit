package seat

import (
	"path/filepath"

	"agentkit/internal/agent"
	"agentkit/internal/config"
	"agentkit/internal/tmux"
)

// Reservations snapshots names once, so editing and drawing a draft need no disk or tmux read.
func (names Names) Reservations() (map[string]bool, bool) {
	taken := map[string]bool{}
	for _, name := range names.held {
		taken[name] = true
	}
	for _, path := range config.SeatFiles() {
		name, _ := config.SeatFileOwner(filepath.Base(path))
		held, known := names.Taken(name)
		if !known {
			return nil, false
		}
		taken[name] = held
	}
	return taken, true
}

// An ordinary tmux session reserves its name but contributes no seat to the screen.
func unrecorded(session tmux.Session) bool {
	return session.Mark != "1" && agent.Agentless(tmux.Own(), []string{session.Name})
}

func opensAt(model config.Model) bool {
	accounts, err := config.Accounts(model.Provider)
	return err == nil && len(accounts) == 0
}
