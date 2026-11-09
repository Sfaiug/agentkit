package seat

import (
	"os"
	"slices"
	"strings"

	"agentkit/internal/config"
	"agentkit/internal/host"
	usages "agentkit/internal/usage"
	"agentkit/internal/worker"
)

// moveLogin is the login a move from `was` onto `next`, the model config.toml calls `model`, runs
// on, as orch._switch_plan picks it: within its provider the seat's own, `account`; onto another,
// the usual login ("") where that one lists no accounts, else the first whose seat login says yes
// of those the readings rank for `model`, then the rest (accountOrder), else DefaultAccount.  Each
// is asked of the adapter at `adapter`, as orch's seat_auth asks it.  False where the login it
// moves on says no, which Python refuses in its words, or where Go cannot rank the readings as
// Python does.
func moveLogin(model string, was, next config.Model, account, adapter string, readings *usages.Readings) (string, bool) {
	subscriptions, err := config.Subscriptions()
	if err != nil {
		return "", false
	}
	var providers []string
	for _, subscription := range subscriptions {
		if subscription.Harness == next.Harness {
			providers = append(providers, subscription.Name)
		}
	}
	login := func(account string) (answered, yes bool) {
		env := append(host.Unmarked(os.Environ()), config.AccountEnv(account), "AGENTKIT_PROVIDER="+strings.Join(providers, " "))
		answered, yes, _ = worker.Login(adapter, env, "seat")
		return answered, yes
	}
	if was.Provider != next.Provider {
		listed, err := config.Accounts(next.Provider)
		if err != nil {
			return "", false
		}
		account = ""
		if len(listed) > 0 {
			home, err := config.SeatAccount(next.Provider)
			if err != nil {
				return "", false
			}
			ranked, err := readings.Held(model, home)
			if err != nil {
				return "", false
			}
			for _, each := range accountOrder(ranked, listed) {
				if answered, yes := login(each); answered && yes {
					return each, true
				}
			}
			account = config.DefaultAccount
		}
	}
	answered, yes := login(account)
	return account, !answered || yes
}

// accountOrder is the order a provider's accounts are tried in for a seat: those ranked for its
// model first, then the rest listed in config order, as orch.account_order leaves them.
func accountOrder(ranked []usages.Account, listed []string) []string {
	var order []string
	for _, account := range ranked {
		order = append(order, account.Name)
	}
	for _, account := range listed {
		if !slices.Contains(order, account) {
			order = append(order, account)
		}
	}
	return order
}
