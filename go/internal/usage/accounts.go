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
// written, else, where none is fresh, every provider asked again, as Python's collect asks. One
// that may not collect (a dry look) reads the snapshot as it stands, as Python's dry tick does.
func SeatAccounts(name, home string, collect bool) ([]Account, error) {
	models, err := config.Entries()
	blob := object(read())
	now := clock()
	at, dated := number(blob.Get("fetched_at"))
	if err != nil {
		return nil, ErrPython
	}
	if collect && (!dated || now-at > cacheTTL) {
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
func (r *Readings) Accounts(name, home string) ([]Account, error) { return r.ranked(name, home, true) }

// Held is Accounts of the subscriptions the reading holds, as orch.account_order ranks only those:
// one it lacks is left out.
func (r *Readings) Held(name, home string) ([]Account, error) { return r.ranked(name, home, false) }

// ranked is Accounts, or Held where not `whole`.
func (r *Readings) ranked(name, home string, whole bool) ([]Account, error) {
	models, now := r.models, r.now
	model := models[name]
	listed, err := config.Accounts(model.Provider)
	if err != nil || len(listed) == 0 {
		return nil, ErrPython
	}
	accounts := object(object(r.providers.Get(model.Provider)).Get("accounts"))
	if whole && len(accounts.Keys()) != len(listed) {
		return nil, ErrPython
	}
	var found []Account
	for _, account := range listed {
		if !whole && !accounts.Has(account) {
			continue
		}
		record := accounts.Dict(account)
		if record == nil {
			return nil, ErrPython
		}
		if rolled(record, now) {
			return nil, ErrPython
		}
		r := &Readings{providers: fields(model.Provider, record), models: models, now: now}
		budget, why := r.Budget(name)
		found = append(found, Account{account, r.Spent(name), r.OnCredits(name), r.low(name), why != "", budget})
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
