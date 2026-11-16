package usage

import (
	"path/filepath"
	"slices"

	"agentkit/internal/config"
	"agentkit/internal/harness"
	"agentkit/internal/run"
)

// Turned keeps what the worker turn of model, in out, reported about the login it ran on,
// TurnAccount's, Python's turns.note_turn_meters: the meters it printed become that login's
// reading.  Best effort and never the turn's failure.
func Turned(model config.Model, account, out string) {
	Reported(model.Provider, account, harness.TurnMeters(model.Harness, out), clock())
}

// Reported makes the meters a worker turn or a seat's status render said, at that moment, about
// the login of provider it ran on that login's reading, Python's usage.record_turn_meters.  The
// usual login goes by two names, "" and DefaultAccount, and is kept where config.toml now lists it:
// a turn begun before its provider's accounts were added or removed still reports about the login
// it ran on.
func Reported(provider, account string, meters []any, at float64) {
	usual := func(account string) bool { return account == "" || account == config.DefaultAccount }
	sources, err := layout()
	found := slices.IndexFunc(sources, func(src source) bool {
		return src.Name == provider && (src.account == account || usual(src.account) && usual(account))
	})
	if err == nil && found >= 0 && len(meters) > 0 {
		keepTurnMeters(sources[found], meters, at)
	}
}

// keepTurnMeters makes the meters a turn reported about its login that login's reading, Python's
// usage._record_turn_meters: a file and no request, so the endpoint's cadence stays as it was and
// only the meters the turn carries are replaced.  It is written under the probe's own lock, so a
// probe in flight cannot write back the reading from before the turn.  Each meter is as old as
// the turn that wrote it (`measured_at`), else as the reading, and one the reading lacks has no
// age: a turn newer on one window leaves another open to an older turn's reading of it.
func keepTurnMeters(src source, meters []any, measured float64) {
	var fresh []*run.Object
	for _, meter := range objects(meters) {
		if _, named := meter.Get("name").(string); named && numbers(meter, "used") {
			fresh = append(fresh, meter)
		}
	}
	if len(fresh) == 0 {
		return
	}
	if held, err := lockFile(filepath.Join(state(), src.key()+"-probe.lock")); err == nil {
		defer held.Close()
	}
	cached := src.cached()
	stood, dated := number(cached.Get("fetched_at"))
	if !dated { // a refused probe's probed_at is fresh and its reading is not
		stood, dated = number(cached.Get("probed_at"))
	}
	if !dated {
		stood = 0
	}
	var old []*run.Object
	held := map[string]any{} // each meter's age, nil for none
	for _, meter := range objects(cached.Get("meters")) {
		name, named := meter.Get("name").(string)
		if !named {
			continue
		}
		meter = meter.Copy()
		switch at, ok := number(meter.Get("measured_at")); {
		case ok && at != 0: // Python's `or`
			meter.Set("measured_at", at)
		case dated:
			meter.Set("measured_at", stood)
		default:
			meter.Set("measured_at", nil)
		}
		old, held[name] = append(old, meter), meter.Get("measured_at")
	}
	fresh = slices.DeleteFunc(fresh, func(meter *run.Object) bool {
		at, aged := number(held[meter.Str("name")])
		return aged && measured <= at
	})
	if len(fresh) == 0 {
		return
	}
	keep(src, fresh, measured, "turn")
	newer, order := map[string]*run.Object{}, []string{}
	for _, meter := range fresh {
		name := meter.Str("name")
		if newer[name] == nil {
			order = append(order, name)
		}
		newer[name] = normalized(meter, measured)
		newer[name].Set("measured_at", measured)
	}
	merged := []any{}
	for _, meter := range old {
		if replaced := newer[meter.Str("name")]; replaced != nil {
			meter = replaced
		}
		merged = append(merged, meter)
	}
	for _, name := range order {
		if _, kept := held[name]; !kept {
			merged = append(merged, newer[name])
		}
	}
	asked := run.NewObject()
	for _, name := range object(cached.Get("probed_meters")).Keys() {
		if at, ok := number(cached.Dict("probed_meters").Get(name)); ok && newer[name] == nil {
			asked.Set(name, at)
		}
	}
	prov := cached.Copy()
	if !prov.Has("provider") {
		prov.Set("provider", src.Name)
	}
	if src.Via != "" && !prov.Has("harness") {
		prov.Set("harness", src.Harness)
	}
	if src.Via != "" && !prov.Has("via") {
		prov.Set("via", src.Via)
	}
	prov.Set("meters", merged)
	prov.Set("probed_at", max(measured, stood))
	prov.Set("probed_meters", asked)
	prov.Set("error", nil)
	prov.Set("pace", topPace(merged))
	for _, key := range []string{"fetched_at", "probe_error", "probe_failed_at", "stale_since"} {
		prov.Delete(key)
	}
	patch(src, prov)
}
