package usage

import (
	"path/filepath"
	"slices"
	"strings"

	"agentkit/internal/config"
	"agentkit/internal/harness"
	"agentkit/internal/run"
)

// Reading is the meters the snapshot holds for that login of the provider now, TurnAccount's,
// Python's usage.reading: what a worker turn measures how far it moved them from.
func Reading(provider, account string) []any {
	return source{Subscription: config.Subscription{Name: provider}, account: account}.cached().List("meters")
}

// Turned keeps what the worker turn of model name in role, in out, reported about the login it ran
// on, TurnAccount's, Python's turns.note_turn_meters: the meters it printed become that login's
// reading, and the tokens it spent beside how far it moved the meters from before, the Reading as
// it began, are a pair of what a window holds, recorded under the turn's model, effort, run and
// role.  Best effort and never the turn's failure.
func Turned(name string, model config.Model, account, role, out string, before []any) {
	sources, err := listed(false)
	at := slices.IndexFunc(sources, func(src source) bool { return src.Name == model.Provider && src.account == account })
	if err != nil || at < 0 {
		return
	}
	src := sources[at]
	meters := harness.TurnMeters(model.Harness, out)
	if len(meters) > 0 {
		keepTurnMeters(src, meters, clock())
	}
	if len(before) == 0 {
		return
	}
	tokens, said := harness.Tokens(model.Harness, out)
	if !said || tokens <= 0 {
		return
	}
	reviewer := strings.HasPrefix(role, "reviewer")
	role = "executor"
	if reviewer {
		role = "reviewer"
	}
	recordPairs(src, name, model.TurnEffort(reviewer), role, filepath.Base(filepath.Dir(filepath.Dir(out))), before, meters, tokens)
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

// recordPairs keeps what one turn spent beside how far it moved each weekly meter gating its model,
// Python's usage.record_pairs.  meters is the reading after the turn, its own, else a probe after
// it, which pairs nothing where the cadence answers with a reading from before the turn ended.  A
// meter pairs only where both readings name the same reset, still ahead, and it did not fall: both
// then lie in the window the turn ran in.  One that did not move pairs the tokens with zero, which
// keeps the estimate from counting only the turns that moved it.
func recordPairs(src source, name, effort, role, runID string, before, meters []any, tokens float64) {
	at := clock()
	if len(meters) == 0 {
		prov := gently(src)
		measured, dated := number(taken(prov))
		if !dated || measured < at {
			return
		}
		meters, at = prov.List("meters"), measured
	}
	models, err := config.Entries()
	if err != nil {
		return
	}
	was := map[string]*run.Object{}
	for _, meter := range objects(before) {
		if title, named := meter.Get("name").(string); named {
			was[title] = meter
		}
	}
	var named []any
	for _, meter := range objects(meters) {
		if _, ok := meter.Get("name").(string); ok {
			named = append(named, meter)
		}
	}
	after := &Readings{providers: fields(src.Name, fields("meters", named)), models: models}
	gating, _ := after.gating(name)
	var read []paired
	for _, meter := range gating {
		old := object(was[meter.Str("name")])
		used, fresh := number(meter.Get("used"))
		prior, began := number(old.Get("used"))
		ends, dated := number(old.Get("resets_at"))
		resets, still := number(meter.Get("resets_at"))
		if session(meter) || !fresh || !began || !dated || !still || resets != ends || ends <= at || used < prior {
			continue
		}
		read = append(read, paired{meter, fields("at", at, "tokens", tokens, "moved", used-prior, "resets_at", ends,
			"prior", prior, "model", name, "effort", effort, "run_id", runID, "role", role)})
	}
	if len(read) > 0 {
		keepPairs(src, read)
	}
}
