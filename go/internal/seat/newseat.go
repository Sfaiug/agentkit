package seat

import (
	"path/filepath"

	"agentkit/internal/config"
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

func opensAt(model config.Model) bool {
	accounts, err := config.Accounts(model.Provider)
	return err == nil && len(accounts) == 0
}
