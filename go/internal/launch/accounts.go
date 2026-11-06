package launch

import "agentkit/internal/config"

// accountTurns is whether a turn here could go out on one of a provider's accounts, config.toml
// listing some: Python's turn picks which (usage.account), and Go's does not yet (worker.Turn).
func accountTurns() bool {
	subs, err := config.Subscriptions()
	if err != nil {
		return true
	}
	for _, sub := range subs {
		if accounts, err := config.Accounts(sub.Name); err != nil || len(accounts) > 0 {
			return true
		}
	}
	return false
}
