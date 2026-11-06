package tick

import (
	"errors"

	"agentkit/internal/config"
	"agentkit/internal/seat"
	"agentkit/internal/worker"
)

// Logout words ask the verb; a failed read decides nothing about the login.
// Answered logins still need Python's recovery and expiry handling.
func quietLogin(live seat.Live) bool {
	if live.Login == nil {
		return !live.Stuck
	}
	adapter, err := config.Adapter(live.Own)
	if errors.Is(err, config.ErrNoAdapterDir) {
		adapter, err = config.ShippedAdapter(live.Own)
	}
	if err != nil {
		return true
	}
	env, err := config.ChildEnv()
	if err != nil {
		return false
	}
	answered, _, _ := worker.Login(adapter, env, "seat")
	return !answered
}
