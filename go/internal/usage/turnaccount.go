package usage

import (
	"cmp"
	"os"
	"slices"

	"agentkit/internal/config"
	"agentkit/internal/run"
)

// TurnAccount is the login a worker turn of that model runs on, and whether it has room, Python's
// usage.account, which each turn of the run at dir asks: "" for a provider listing none.  Its
// logins rank as workerRank ranks them for this model, and where the seat the run was launched
// from has its orchestrator on that provider, the seat's own login goes last: it is used only once
// every other is spent for the model or its `auth` says it cannot run.  With none of them read
// yet, it is the first listed but the usual one.
func TurnAccount(name, dir string) (string, bool, error) {
	model, err := config.ModelNamed(name)
	if err != nil {
		return "", false, err
	}
	listed, err := config.Accounts(model.Provider)
	if err != nil || len(listed) == 0 {
		return "", false, err
	}
	readings, err := Read()
	if err != nil {
		return "", false, err
	}
	prov := object(readings.providers.Get(model.Provider))
	if !slices.Contains(listed, prov.Str("account")) {
		spare := listed[0]
		if at := slices.IndexFunc(listed, func(account string) bool { return account != config.DefaultAccount }); at >= 0 {
			spare = listed[at]
		}
		return spare, !prov.Truthy("exhausted"), nil
	}
	accounts := prov.Dict("accounts")
	alone := func(account string) *Readings {
		return &Readings{providers: fields(model.Provider, accounts.Dict(account)), models: readings.models, now: readings.now}
	}
	spent := func(account string) bool { return alone(account).Spent(name) != "" }
	ranks, order := map[string][]float64{}, accounts.Keys()
	for _, account := range order {
		reading := accounts.Dict(account)
		// one whose meters ak cannot read may be logged out: it is no safer than one running low
		ranks[account] = workerRank(account, reading, reading.Get("budget_reason") != nil || alone(account).low(name))
	}
	slices.SortStableFunc(order, func(a, b string) int { return slices.Compare(ranks[a], ranks[b]) })
	seat, err := launching(dir)
	if err != nil {
		return "", false, err
	}
	orchestrator, _ := seat["orchestrator"].(string)
	own, _ := seat["account"].(string)
	own = cmp.Or(own, config.DefaultAccount)
	if readings.models[orchestrator].Provider != model.Provider || !accounts.Has(own) {
		return order[0], !spent(order[0]), nil
	}
	adapter, err := config.Adapter(model.Harness)
	refused := func(account string) bool {
		if err != nil { // no adapter to ask says nothing, as Python's worker.auth_ok
			return false
		}
		answered, yes := auth(adapter, model.Provider, account)
		return answered && !yes
	}
	for _, account := range order {
		if account != own && !spent(account) && !refused(account) {
			return account, true, nil
		}
	}
	return own, !spent(own), nil
}

// launching is the record of the seat the run at dir was launched from, nil for none: its
// launched_session, else its session, so a launch from no seat stays seatless wherever it is
// resumed; where no run is asking, or its record names neither, the seat AGENTKIT_SESSION names.
func launching(dir string) (map[string]any, error) {
	name := os.Getenv("AGENTKIT_SESSION")
	if dir != "" {
		if record, _ := run.Read(dir); record != nil && (record.Has("launched_session") || record.Has("session")) {
			name = run.Launched(record)
		}
	}
	if name == "" {
		return nil, nil
	}
	_, seat, err := config.ResolveSession(name)
	return seat, err
}
