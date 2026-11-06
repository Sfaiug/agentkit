package worker

import (
	"errors"

	"agentkit/internal/box"
	"agentkit/internal/config"
)

// Adapter is the adapter a turn of that model runs, ErrPython where the turn is Python's: asked
// before anything is written for it, so a caller hands over with nothing to undo.
func Adapter(model config.Model) (string, error) {
	adapter, err := config.Adapter(model.Harness)
	accounts, _ := config.Accounts(model.Provider)
	if !box.Supported || errors.Is(err, config.ErrNoAdapterDir) || len(accounts) > 0 || config.EnsureDirs() != nil {
		return "", ErrPython
	}
	return adapter, err
}
