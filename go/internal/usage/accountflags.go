package usage

import (
	"slices"

	"agentkit/internal/config"
	"agentkit/internal/run"
)

// flagAccounts flags a provider listing accounts as Python's usage._gate_flags does: each account
// on its own, then the provider as the one a worker turn runs on next -- another account with room
// before the usual login, the usual one only when none has any, then the most budget, then the
// order the config lists them in -- with the accounts beside it, so it is spent only when all are.
func flagAccounts(name string, prov *run.Object, now float64, models map[string]config.Model) {
	listed, _ := config.Accounts(name)
	accounts, ok := prov.Get("accounts").(*run.Object)
	if len(listed) == 0 || !ok {
		return
	}
	flagged := run.NewObject()
	for _, account := range listed {
		if each, ok := accounts.Get(account).(*run.Object); ok {
			flagged.Set(account, each)
		}
	}
	gateFlags(flagged, now, models)
	best := ""
	for _, account := range flagged.Keys() {
		if best == "" || slices.Compare(workerRank(account, flagged.Dict(account)), workerRank(best, flagged.Dict(best))) < 0 {
			best = account
		}
	}
	if best == "" {
		return
	}
	for _, key := range prov.Keys() {
		prov.Delete(key)
	}
	for _, key := range flagged.Dict(best).Keys() {
		prov.Set(key, flagged.Dict(best).Get(key))
	}
	prov.Set("accounts", flagged)
	prov.Set("account", best)
}

// workerRank is where a flagged account stands for a worker turn, lowest first (usage._worker_rank):
// spent last, then on credits, then the usual login and any unread one after the others with room,
// then the most budget.  An unread account ranks with the usual login: its login may be what failed.
func workerRank(account string, reading *run.Object) []float64 {
	spent, unknown := reading.Truthy("exhausted"), reading.Get("budget_reason") != nil
	group := 0.0
	switch {
	case account == config.DefaultAccount || unknown && !spent:
		group = 1
	case spent:
		group = 2
	}
	budget, _ := number(reading.Get("budget"))
	yes := map[bool]float64{true: 1}
	return []float64{yes[spent], yes[reading.Truthy("on_credits")], group, yes[unknown], -budget}
}
