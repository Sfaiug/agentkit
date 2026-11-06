package seat

import (
	"maps"
	"path/filepath"
	"slices"

	"agentkit/internal/config"
)

// Reservations is Taken for every name that can be taken, read once, so editing and drawing a
// draft need no disk or tmux read.
func (names Names) Reservations() (map[string]bool, bool) {
	named := slices.Concat(names.held, slices.Collect(maps.Keys(names.seats)))
	for _, path := range config.SeatFiles() {
		name, _ := config.SeatFileOwner(filepath.Base(path))
		named = append(named, name)
	}
	taken := map[string]bool{}
	for _, name := range named {
		reserved, known := names.Taken(name)
		if !known {
			return nil, false
		}
		taken[name] = reserved
	}
	return taken, true
}

func opensAt(model config.Model) bool {
	accounts, err := config.Accounts(model.Provider)
	return err == nil && len(accounts) == 0
}
