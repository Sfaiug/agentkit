// Package usage reads each subscription's meters, Python's agentkit/usage.py, and answers what a
// pick asks of them: whether a model has room, its budget and whether it runs on credits.  It
// hides how: each provider's adapter asked through its `usage` verb, and its `auth` verb where
// that answers an error, at most once in its harness's cadence under the provider's probe lock;
// state/usage.json, written whole under its own lock in Python's format; and the five minutes a
// reading answers from that file without asking anybody.
package usage

import (
	"errors"
	"path/filepath"
	"time"

	"agentkit/internal/config"
	"agentkit/internal/run"
)

// ErrPython is a home whose usage Python ak reads: where its adapter scripts live is not yet
// Go's.
var ErrPython = errors.New("left to Python")

// Readings is every provider's reading, as of the moment it was read.
type Readings struct {
	providers *run.Object
	sources   []source
	models    map[string]config.Model
	now       float64
}

// A source is a provider as the read asks it: its table, its harness's `[usage]` facts, the
// adapter script that answers for it or why none can, and the account of it asked, "" for its one
// login.
type source struct {
	config.Subscription
	facts   config.UsageFacts
	adapter string
	broken  error
	account string
}

// key is what the source's probe moment and its not-before are kept under: its provider's name, an
// account's after a dot (usage._lock).
func (src source) key() string {
	if src.account == "" {
		return src.Name
	}
	return src.Name + "." + src.account
}

// Read is the reading of every provider config.toml lists: the one state/usage.json holds while
// it is under five minutes old, else each provider's adapter asked again, as Python's
// usage.collect reads it.  ErrPython before anything is locked or asked.
func Read() (*Readings, error) { return readAll(false) }

// Collected is Read as Python's tick and its marks read it, the checkout's own adapters asked
// where no $AGENTKIT_ADAPTER_DIR is named, as the ak screen asks them.
func Collected() (*Readings, error) { return readAll(true) }

func readAll(shipped bool) (*Readings, error) {
	sources, err := listed(shipped)
	if err != nil {
		return nil, err
	}
	models, err := config.Entries()
	if err != nil {
		return nil, err
	}
	providers, err := collect(sources, models, false)
	return &Readings{providers, sources, models, clock()}, err
}

// Check is Read's ErrPython, nothing asked: a launch settles it before it writes anything.
func Check() error {
	_, err := listed(false)
	return err
}

// listed is every login config.toml lists as a read asks it, a provider's one or each account it
// lists, as Python does, or why that is not Go's; a refresh asks, where no $AGENTKIT_ADAPTER_DIR
// is named, the checkout's own adapters.
func listed(refresh bool) ([]source, error) {
	subs, err := config.Subscriptions()
	if err != nil {
		return nil, err
	}
	var sources []source
	for _, sub := range subs {
		facts, err := config.Usage(sub.Harness)
		if err != nil {
			return nil, err
		}
		accounts, err := config.Accounts(sub.Name)
		if err != nil {
			return nil, err
		}
		adapter, err := config.Adapter(sub.Harness)
		if errors.Is(err, config.ErrNoAdapterDir) && refresh {
			adapter, err = config.ShippedAdapter(sub.Harness)
		}
		if errors.Is(err, config.ErrNoAdapterDir) {
			return nil, ErrPython
		}
		if len(accounts) == 0 {
			accounts = []string{""} // the provider's one login
		}
		for _, account := range accounts {
			sources = append(sources, source{sub, facts, adapter, err, account})
		}
	}
	return sources, nil
}

// Spent is why nothing is picked on that model, Python's usage.model_exhausted: its provider
// refused a worker and is parked, or a meter gating it reads 100% used with no credits left; ""
// where something may be.
func (r *Readings) Spent(name string) string {
	meters, prov := r.gating(name)
	if until, ok := number(prov.Get("exhausted_until")); ok && until > r.now && !freshWindow(prov, prov, r.now) {
		return r.models[name].Provider + " ran dry; nothing is picked on it until " + local(until).Format("2006-01-02 15:04")
	}
	var worst *run.Object
	for _, meter := range meters {
		if used(meter) >= 100 && (worst == nil || used(meter) > used(worst)) {
			worst = meter
		}
	}
	if worst == nil || creditsLeft(prov) > 0 {
		return ""
	}
	return text(worst.Get("name")) + " " + text(worst.Get("used")) + "% used >= 100"
}

// Budget is that model's budget on the meters gating it and why its reading cannot tell, ""
// where it can, Python's usage.model_budget.
func (r *Readings) Budget(name string) (float64, string) {
	meters, prov := r.gating(name)
	gated := prov.Copy()
	gated.Set("meters", list(meters))
	return providerBudget(gated, r.now)
}

// OnCredits is whether that model runs on its provider's credits, a meter it watches spent,
// Python's usage.on_credits.
func (r *Readings) OnCredits(name string) bool {
	meters, prov := r.gating(name)
	if creditsLeft(prov) == 0 {
		return false
	}
	named := map[string]bool{}
	for _, meter := range meters {
		named[meter.Str("name")] = true
	}
	for _, meter := range objects(prov.Get("meters")) {
		if session(meter) && !named[meter.Str("name")] {
			meters = append(meters, meter)
		}
	}
	for _, meter := range meters {
		if used(meter) >= 100 {
			return true
		}
	}
	return false
}

// Shown is every reading as `ak usage --json` prints it: each login's with what its shared week
// holds in tokens and how many pairs measure it (holds), its price a month and what a million
// tokens cost at it.
func (r *Readings) Shown() *run.Object {
	for _, each := range r.logins() {
		price := r.source(each.provider).Price
		shared := r.sharedWeek(each.provider, each.prov)
		tokens, pairs := holds(each.provider, each.account, shared)
		each.prov.Set("capacity_tokens", tokens)
		each.prov.Set("capacity_pairs", pairs)
		each.prov.Set("price", nil)
		if price != nil {
			each.prov.Set("price", *price)
		}
		each.prov.Set("price_per_1m", perMillion(price, tokens, shared))
	}
	return r.providers
}

// gating is the meters that gate that model and its provider's reading, Python's
// usage._gating_meters: the model's own `meter`, the shared week and the session where it names
// one, else every meter no other model of its provider claims.
func (r *Readings) gating(name string) ([]*run.Object, *run.Object) {
	model := r.models[name]
	prov := object(r.providers.Get(model.Provider))
	claimed := map[string]bool{}
	for other, entry := range r.models {
		if other != name && entry.Meter != "" && entry.Provider == model.Provider {
			claimed[entry.Meter] = true
		}
	}
	var meters []*run.Object
	for _, meter := range objects(prov.Get("meters")) {
		if model.Meter != "" && (meter.Str("name") == model.Meter || meter.Str("name") == "weekly_all" || session(meter)) ||
			model.Meter == "" && !claimed[meter.Str("name")] {
			meters = append(meters, meter)
		}
	}
	return meters, prov
}

func state() string {
	return filepath.Join(config.Home(), "state")
}

// clock is now as Python's time.time() reads it.
func clock() float64 {
	return float64(time.Now().UnixNano()) / 1e9
}
