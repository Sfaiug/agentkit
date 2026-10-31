// Package usage reads each subscription's meters, Python's agentkit/usage.py, and answers what a
// pick asks of them: whether a model has room, its budget and whether it runs on credits.  It
// hides how: each provider's adapter asked through its `usage` verb, and its `auth` verb where
// that answers an error, at most once in its harness's cadence under the provider's probe lock;
// state/usage.json, written whole under its own lock in Python's format; and the five minutes a
// reading answers from that file without asking anybody.
package usage

import (
	"errors"
	"os"
	"path/filepath"
	"time"

	"agentkit/internal/config"
	"agentkit/internal/run"
)

// ErrPython is a home whose usage Python ak reads: where its adapter scripts live, a provider
// listing accounts, a harness whose probe runs a model, says no time or counts the resets the
// owner spends, and the tokens a window holds measured in state/capacity.json are not yet Go's.
var ErrPython = errors.New("left to Python")

// Readings is every provider's reading, as of the moment it was read.
type Readings struct {
	providers *run.Object
	sources   []source
	models    map[string]config.Model
	now       float64
}

// A source is a provider as the read asks it: its table and its harness's `[usage]` facts.
type source struct {
	config.Subscription
	facts config.UsageFacts
}

// Read is the reading of every provider config.toml lists: the one state/usage.json holds while
// it is under five minutes old, else each provider's adapter asked again, as Python's
// usage.collect reads it.  ErrPython before anything is locked or asked.
func Read() (*Readings, error) {
	subs, err := config.Subscriptions()
	if err != nil {
		return nil, err
	}
	models, err := config.Models()
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
		_, err = config.Adapter(sub.Harness)
		if errors.Is(err, config.ErrNoAdapterDir) || len(accounts) > 0 || facts.Capture || facts.StripsTimestamp || facts.Reset {
			return nil, ErrPython
		}
		sources = append(sources, source{sub, facts})
	}
	if measured() {
		return nil, ErrPython
	}
	providers, err := collect(sources, models)
	return &Readings{providers, sources, models, clock()}, err
}

// Spent is whether a meter gating that model reads 100% used with no credits left, or its
// provider refused a worker and is parked, Python's usage.model_exhausted.
func (r *Readings) Spent(name string) bool {
	meters, prov := r.gating(name)
	if until, ok := number(prov.Get("exhausted_until")); ok && until > r.now && !freshWindow(prov, prov, r.now) {
		return true
	}
	for _, meter := range meters {
		if used(meter) >= 100 {
			return creditsLeft(prov) == 0
		}
	}
	return false
}

// Budget is that model's budget on the meters gating it, false where it is unknown, Python's
// usage.model_budget.
func (r *Readings) Budget(name string) (float64, bool) {
	meters, prov := r.gating(name)
	gated := prov.Copy()
	gated.Set("meters", list(meters))
	budget, why := providerBudget(gated, r.now)
	return budget, why == ""
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

// Shown is every reading as `ak usage --json` prints it: each with its price a month, and with
// what its week holds in tokens and what a million of them cost, which no capacity.json reading
// measures (Read).
func (r *Readings) Shown() *run.Object {
	for _, src := range r.sources {
		prov, ok := r.providers.Get(src.Name).(*run.Object)
		if !ok {
			continue
		}
		records := []*run.Object{prov}
		if accounts, ok := prov.Get("accounts").(*run.Object); ok && len(accounts.Keys()) > 0 {
			records = objects(values(accounts))
		}
		for _, record := range records {
			record.Set("capacity_tokens", nil)
			record.Set("capacity_pairs", 0)
			record.Set("price", nil)
			if src.Price != nil {
				record.Set("price", *src.Price)
			}
			record.Set("price_per_1m", nil)
		}
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

// measured is whether state/capacity.json holds a pair of a turn's tokens and how far it moved a
// meter, from which Python's usage.holds measures what a window holds.
func measured() bool {
	data, err := os.ReadFile(filepath.Join(state(), "capacity.json"))
	if err != nil {
		return false
	}
	held, _ := run.Decode(data)
	for _, accounts := range values(object(held)) {
		for _, meters := range values(object(accounts)) {
			for _, pairs := range values(object(meters)) {
				for _, pair := range objects(pairs) {
					if numbers(pair, "at", "tokens", "moved", "resets_at") {
						return true
					}
				}
			}
		}
	}
	return false
}

func state() string {
	return filepath.Join(config.Home(), "state")
}

// clock is now as Python's time.time() reads it.
func clock() float64 {
	return float64(time.Now().UnixNano()) / 1e9
}
