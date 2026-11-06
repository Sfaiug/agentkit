package usage

import (
	"cmp"
	"slices"

	"agentkit/internal/config"
)

// Account is one subscription ranked for this model alone, as orch.account_order ranks it.
type Account struct {
	Name, Spent           string
	Credits, Low, Unknown bool
	Budget                float64
}

// SeatAccounts is Accounts as seat_account reads them: a fresh snapshot's, nothing probed or
// written, else, where none is fresh, every provider asked again, as Python's collect asks.
func SeatAccounts(name, home string) ([]Account, error) {
	models, err := config.Entries()
	blob := object(read())
	now := clock()
	at, dated := number(blob.Get("fetched_at"))
	if err != nil {
		return nil, ErrPython
	}
	if !dated || now-at > cacheTTL {
		readings, err := Collected()
		if err != nil {
			return nil, err
		}
		return readings.Accounts(name, home)
	}
	return (&Readings{providers: object(blob.Get("providers")), models: models, now: now}).Accounts(name, home)
}

// Accounts is each subscription of that model's provider ranked for this model alone, home first
// while it has room for it, as orch.account_order ranks them; ErrPython where the reading lacks
// one, or holds one past its reset.
func (r *Readings) Accounts(name, home string) ([]Account, error) {
	models, now := r.models, r.now
	model := models[name]
	listed, err := config.Accounts(model.Provider)
	if err != nil || len(listed) == 0 {
		return nil, ErrPython
	}
	accounts := object(object(r.providers.Get(model.Provider)).Get("accounts"))
	if len(accounts.Keys()) != len(listed) {
		return nil, ErrPython
	}
	sources, err := config.Subscriptions()
	if err != nil {
		return nil, err
	}
	own := model.Harness
	for _, src := range sources {
		if src.Name == model.Provider {
			own = src.Harness
			break
		}
	}
	facts, err := config.Usage(own)
	if err != nil {
		return nil, err
	}
	every := facts.ProbeEvery
	if every <= 0 {
		every = 60
	}
	var found []Account
	for _, account := range listed {
		record := accounts.Dict(account)
		if record == nil {
			return nil, ErrPython
		}
		if rolled(record, now) {
			return nil, ErrPython
		}
		r := &Readings{providers: fields(model.Provider, record), models: models, now: now}
		budget, why := r.Budget(name)
		low := false
		meters, _ := r.gating(name)
		for _, meter := range meters {
			used, known := number(meter.Get("used"))
			elapsed, _ := number(meter.Get("elapsed"))
			window, _ := number(meter.Get("window_secs"))
			floor := 5.0
			if elapsed > 0 && window > 0 {
				floor = max(floor, used/(elapsed/100*window)*every)
			}
			low = low || known && 100-used < floor
		}
		found = append(found, Account{account, r.Spent(name), r.OnCredits(name), low, why != "", budget})
	}
	slices.SortStableFunc(found, func(a, b Account) int {
		for _, pair := range [][2]bool{{a.Spent != "", b.Spent != ""}, {a.Credits, b.Credits}, {a.Low, b.Low}, {a.Unknown, b.Unknown}} {
			if pair[0] != pair[1] {
				if pair[0] {
					return 1
				}
				return -1
			}
		}
		return cmp.Compare(b.Budget, a.Budget)
	})
	if at := slices.IndexFunc(found, func(a Account) bool { return a.Name == home && a.Spent == "" && !a.Credits && !a.Low }); at >= 0 {
		first := found[at]
		found = append([]Account{first}, append(found[:at], found[at+1:]...)...)
	}
	return found, nil
}
