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
// reading.  Best effort and never the turn's failure.  The usual login goes by two names, "" and
// DefaultAccount, and is kept where config.toml now lists it: a turn begun before its provider's
// accounts were added or removed still reports about the login it ran on.
func Turned(model config.Model, account, out string) {
	usual := func(account string) bool { return account == "" || account == config.DefaultAccount }
	sources, err := listed(false)
	at := slices.IndexFunc(sources, func(src source) bool {
		return src.Name == model.Provider && (src.account == account || usual(src.account) && usual(account))
	})
	if err != nil || at < 0 {
		return
	}
	if meters := harness.TurnMeters(model.Harness, out); len(meters) > 0 {
		keepTurnMeters(sources[at], meters, clock())
	}
}

// keepTurnMeters makes the meters a turn reported about its login that login's reading, Python's
// usage.record_turn_meters: a file and no request, so the endpoint's cadence stays as it was and
// only the meters the turn carries are replaced.  It is written under the probe's own lock, so a
// probe in flight cannot write back the reading from before the turn, and never over a newer one.
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
	if dated && measured <= stood {
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
	}
	merged, kept := []any{}, map[string]bool{}
	for _, meter := range objects(cached.Get("meters")) {
		name, named := meter.Get("name").(string)
		if !named {
			continue
		}
		if replaced := newer[name]; replaced != nil {
			meter = replaced
		}
		merged, kept[name] = append(merged, meter), true
	}
	for _, name := range order {
		if !kept[name] {
			merged = append(merged, newer[name])
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
	prov.Set("probed_at", measured)
	prov.Set("error", nil)
	prov.Set("pace", topPace(merged))
	for _, key := range []string{"fetched_at", "probe_error", "probe_failed_at", "stale_since"} {
		prov.Delete(key)
	}
	patch(src, prov)
}
