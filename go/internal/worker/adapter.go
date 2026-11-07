package worker

import (
	"errors"
	"slices"

	"agentkit/internal/box"
	"agentkit/internal/config"
)

// Adapter is the adapter a turn of that model on account runs, ErrPython where the turn is
// Python's: it only reads, so a caller asks it before writing anything and hands over with nothing
// to undo.
func Adapter(model config.Model, account string) (string, error) {
	adapter, err := config.Adapter(model.Harness)
	accounts, _ := config.Accounts(model.Provider)
	if !box.Supported || errors.Is(err, config.ErrNoAdapterDir) || len(accounts) > 0 && !slices.Contains(accounts, account) {
		return "", ErrPython
	}
	return adapter, err
}
