package seat

import (
	"os"
	"slices"
	"strings"

	"agentkit/internal/adapters"
	"agentkit/internal/config"
	"agentkit/internal/host"
	usages "agentkit/internal/usage"
	"agentkit/internal/worker"
)

// moveLogin is the login a move from `was` onto `next`, the model config.toml calls `model`, runs
// on, as orch._switch_plan picks it: within its provider the seat's own, `account`; onto another,
// the usual login ("") where that one lists no accounts, else the first whose seat login passes
// (workingAccount) of those the readings rank for `model`, then the rest, else DefaultAccount.
// A login no seat login passed yet is asked of the adapter at `adapter`.  False where it says no,
// which Python refuses in its words, or where Go cannot rank the readings as Python does.
func moveLogin(model string, was, next config.Model, account, adapter string, readings *usages.Readings) (string, bool) {
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
			if found := workingAccount(next.Harness, ranked, listed); found != "" {
				return found, true
			}
			account = config.DefaultAccount
		}
	}
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
	env := append(host.Unmarked(os.Environ()), config.AccountEnv(account), "AGENTKIT_PROVIDER="+strings.Join(providers, " "))
	answered, yes, _ := worker.Login(adapter, env, "seat")
	return account, !answered || yes
}

// workingAccount is the first of a provider's accounts whose seat login passes (adapters.SeatAuth):
// those ranked for its model first, then the rest listed in config order, as orch.account_order
// leaves them; "" for none.
func workingAccount(own string, ranked []usages.Account, listed []string) string {
	var order []string
	for _, account := range ranked {
		order = append(order, account.Name)
	}
	for _, account := range listed {
		if !slices.Contains(order, account) {
			order = append(order, account)
		}
	}
	for _, account := range order {
		if adapters.SeatAuth(own, account) {
			return account
		}
	}
	return ""
}
