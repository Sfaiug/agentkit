package launch

import (
	"agentkit/internal/config"
	"agentkit/internal/usage"
)

// accountTurns is whether a turn here could go out on a login Go does not pick (usage.TurnAccount):
// one of several a provider lists, which Python's turn picks.
func accountTurns() bool {
	subs, err := config.Subscriptions()
	if err != nil {
		return true
	}
	for _, sub := range subs {
		if _, err := usage.TurnAccount(sub.Name); err != nil {
			return true
		}
	}
	return false
}
