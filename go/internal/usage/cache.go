package usage

import (
	"cmp"
	"context"
	"fmt"
	"os"
	"path/filepath"
	"slices"
	"sync/atomic"

	"agentkit/internal/config"
	"agentkit/internal/lock"
	"agentkit/internal/run"
)

const cacheTTL = 300.0 // seconds a snapshot answers for without asking any adapter

// mark is a refusal's fields on a record, which only the refusal that makes them writes.
var mark = []string{"exhausted_until", "exhausted_at", "exhausted_ends", "exhausted_by"}

// collect is every provider's record, Python's usage.collect: the snapshot's while it is under
// cacheTTL old, a provider with a meter past its reset or accounts it no longer lists asked
// again, else every provider asked.
func collect(sources []source, models map[string]config.Model) (*run.Object, error) {
	now := clock()
	blob := object(read())
	held, cached := blob.Get("providers").(*run.Object)
	if at, ok := run.Num(blob.Get("fetched_at")); ok && now-at <= cacheTTL && cached {
		listed := map[string]source{}
		for _, src := range sources {
			listed[src.Name] = src
		}
		providers := run.NewObject()
		for _, name := range held.Keys() {
			if _, ok := listed[name]; ok {
				providers.Set(name, object(held.Get(name)))
			}
		}
		stored, counted := false, map[string]float64{}
		for _, name := range providers.Keys() {
			prov := providers.Dict(name)
			if prov.Truthy("accounts") || rolled(prov, now) {
				prov = withoutPast(gently(listed[name]), now, "the adapter")
				providers.Set(name, prov)
				stored = true
			}
			if !numbers(prov, "resets") {
				stored = true
				if listed[name].Via != "" { // its harness counts no usage-limit resets (Read): none held
					counted[name] = 0
					prov.Set("resets", 0.0)
				}
			}
		}
		var err error
		if stored {
			providers, err = store(sources, providers, models, now, nil, counted)
		}
		return gateFlags(providers, now, models), err
	}
	providers := run.NewObject()
	for _, src := range sources {
		providers.Set(src.Name, withoutPast(gently(src), now, "the adapter"))
	}
	providers, err := store(sources, providers, models, now, &now, nil)
	return gateFlags(providers, now, models), err
}

// rolled is whether a meter of that record is past its reset.
func rolled(prov *run.Object, now float64) bool {
	return slices.ContainsFunc(objects(prov.Get("meters")), func(meter *run.Object) bool { return past(meter, now) })
}

// store writes what collect answers, each provider's record as the snapshot holds it now, a
// copy of providers standing in only where it holds none, and a provider config.toml no longer
// lists gone, Python's usage._store; fetchedAt dates the snapshot where given.
func store(sources []source, providers *run.Object, models map[string]config.Model, now float64, fetchedAt *float64, counted map[string]float64) (*run.Object, error) {
	return write(func(disk *run.Object, _ float64) *run.Object {
		for _, name := range disk.Keys() {
			if !slices.ContainsFunc(sources, func(src source) bool { return src.Name == name }) {
				disk.Delete(name)
			}
		}
		answer := run.NewObject()
		for _, name := range providers.Keys() {
			prov, ok := disk.Get(name).(*run.Object)
			if !ok {
				prov = object(providers.Get(name))
			}
			if rolled(prov, now) {
				prov = withoutPast(prov, now, "the adapter")
			} else {
				prov = prov.Copy()
			}
			if resets, ok := counted[name]; ok && !numbers(prov, "resets") {
				prov.Set("resets", resets)
			}
			disk.Set(name, prov)
			answer.Set(name, prov)
		}
		return gateFlags(answer, now, models)
	}, fetchedAt)
}

// patch puts one freshly read provider into the snapshot as it stands now, the others and its
// age left alone, and is the record as written, Python's usage._patch.
func patch(name string, prov *run.Object) *run.Object {
	change := func(providers *run.Object, now float64) *run.Object {
		record := onto(object(providers.Get(name)), prov, now)
		providers.Set(name, record)
		return record
	}
	record, err := write(change, nil)
	if err != nil { // a snapshot that cannot be written costs a re-probe
		return change(run.NewObject(), clock())
	}
	return record
}

var writes atomic.Int64 // a temporary name of each write's own

// write changes the snapshot as it stands under its lock and writes it back whole, through a
// temporary name, Python's usage._write: its age stays as it was unless fetchedAt dates it,
// and it keeps the last two windows each weekly meter named.
func write(change func(providers *run.Object, now float64) *run.Object, fetchedAt *float64) (*run.Object, error) {
	held, err := lockFile(filepath.Join(state(), "usage.lock"))
	if err != nil {
		return nil, err
	}
	defer held.Close()
	blob, providers := run.NewObject(), run.NewObject()
	if read, ok := read().(*run.Object); ok {
		if kept, ok := read.Get("providers").(*run.Object); ok {
			blob, providers = read, kept.Copy()
		}
	}
	out := change(providers, clock())
	fetched, _ := number(blob.Get("fetched_at"))
	if fetchedAt != nil {
		fetched = *fetchedAt
	}
	cache := filepath.Join(state(), "usage.json")
	tmp := filepath.Join(state(), fmt.Sprintf("usage.tmp-%d-%d", os.Getpid(), writes.Add(1)-1))
	defer os.Remove(tmp)
	snapshot := fields("fetched_at", fetched, "providers", providers, "windows", windows(blob.Get("windows"), providers))
	if err := os.WriteFile(tmp, []byte(run.Line(snapshot)), 0o666); err != nil {
		return nil, err
	}
	return out, os.Rename(tmp, cache)
}

// read is the snapshot's JSON, nil where there is none to read.
func read() any {
	data, err := os.ReadFile(filepath.Join(state(), "usage.json"))
	if err != nil {
		return nil
	}
	value, _ := run.Decode(data)
	return value
}

// cachedProvider is what the snapshot holds for that provider now, read off the file to see
// what another process wrote while this one waited for its lock.
func cachedProvider(name string) *run.Object {
	return object(object(object(read()).Get("providers")).Get(name))
}

// lockFile is path's lock under state/, once it is free.
func lockFile(path string) (*os.File, error) {
	if err := config.EnsureDirs(); err != nil {
		return nil, err
	}
	return lock.Wait(context.Background(), path)
}

// kept is fresh where the adapter answered with meters, or the meterless answer of a harness
// that reads none, else the reading it could not replace with the failed ask written beside it,
// Python's usage._kept.
func kept(cached, fresh *run.Object, now float64) *run.Object {
	if fresh.Truthy("meters") || fresh.Truthy("none") {
		meters, added := beside(cached.List("meters"), fresh.List("meters"), now)
		if !added {
			return fresh
		}
		out := fresh.Copy()
		out.Set("meters", meters)
		out.Set("fetched_at", taken(cached))
		return out
	}
	since, ok := number(cached.Get("stale_since"))
	keys := []string{"meters", "fetched_at", "resets", "credits", "currency", "error", "notes", "none", "none_reason"}
	if cached.Truthy("none") || !cached.Truthy("meters") {
		// no reading to keep, so nothing overwrites the ask's own error
		keys = slices.DeleteFunc(keys, func(key string) bool { return key == "error" })
	}
	out := fresh.Copy()
	for _, key := range keys {
		if cached.Has(key) {
			out.Set(key, cached.Get(key))
		}
	}
	out.Set("fetched_at", taken(cached))
	out.Set("probe_error", fresh.Get("error"))
	out.Set("probe_failed_at", now)
	if !ok || !cached.Truthy("probe_error") {
		since = now
	}
	out.Set("stale_since", since)
	return out
}

// beside is fresh, and where every meter of it is spent, each of old's in a window it does not
// name, Python's usage._beside: a refusal says nothing of the other windows.
func beside(old, fresh []any, now float64) ([]any, bool) {
	if len(fresh) == 0 {
		return fresh, false
	}
	var named []any
	for _, meter := range objects(fresh) {
		if used(meter) < 100 {
			return fresh, false
		}
		named = append(named, meter.Get("window_secs"))
	}
	var kept []any
	for _, meter := range objects(old) {
		if numbers(meter, "used") && !past(meter, now) &&
			!slices.ContainsFunc(named, func(window any) bool { return run.Equal(window, meter.Get("window_secs")) }) {
			kept = append(kept, meter)
		}
	}
	if len(kept) == 0 {
		return fresh, false
	}
	return append(slices.Clone(fresh), kept...), true
}

// taken is when a reading was measured, Python's usage._taken: its fetched_at, else, where no
// reading ever wrote that down, the last ask's probed_at; nil where neither is a number.
func taken(prov *run.Object) any {
	at := prov.Get("probed_at")
	if prov.Has("fetched_at") {
		at = prov.Get("fetched_at")
	}
	if value, ok := number(at); ok {
		return run.Float(value)
	}
	return nil
}

// onto is a writer's reading over the record the snapshot holds, with that record's mark while it
// is in force, Python's usage._onto.
func onto(old, prov *run.Object, now float64) *run.Object {
	prov = prov.Copy()
	for _, key := range mark {
		prov.Delete(key)
	}
	until, ok := number(old.Get("exhausted_until"))
	if !ok || until <= now || freshWindow(prov, old, now) {
		return prov
	}
	prov.Set("exhausted_until", until)
	if at, ok := number(old.Get("exhausted_at")); ok {
		prov.Set("exhausted_at", at)
	}
	if ends, ok := old.Get("exhausted_ends").(*run.Object); ok {
		prov.Set("exhausted_ends", ends)
	}
	if by, ok := old.Get("exhausted_by").(string); ok {
		prov.Set("exhausted_by", by)
	}
	return prov
}

// freshWindow is whether the meter that showed the refusal marked reports a later reset with
// room left, Python's usage._fresh_window.
func freshWindow(prov, marked *run.Object, now float64) bool {
	ends, ok := marked.Get("exhausted_ends").(*run.Object)
	if !ok {
		return false
	}
	for _, meter := range objects(prov.Get("meters")) {
		if !run.Equal(meter.Get("name"), marked.Get("exhausted_by")) {
			continue
		}
		used, numeric := number(meter.Get("used"))
		resets, dated := number(meter.Get("resets_at"))
		title, named := meter.Get("name").(string)
		old, recorded := number(ends.Get(title))
		if numeric && used < 100 && dated && resets > now && named && recorded && resets > old {
			return true
		}
	}
	return false
}

// windows is the ends of the last two windows each weekly meter of each subscription named:
// seen, what the snapshot held, and the readings of providers, Python's usage._windows.
func windows(seen any, providers *run.Object) *run.Object {
	kept := run.NewObject()
	for _, name := range providers.Keys() {
		kept.Set(name, object(object(seen).Get(name)))
	}
	for _, name := range providers.Keys() {
		prov := object(providers.Get(name))
		logins := run.NewObject() // each account's record, the usual login's for a provider of one
		logins.Set("default", prov)
		if accounts, ok := prov.Get("accounts").(*run.Object); ok && len(accounts.Keys()) > 0 {
			logins = run.NewObject()
			for _, account := range accounts.Keys() {
				logins.Set(cmp.Or(account, "default"), object(accounts.Get(account)))
			}
		}
		for _, key := range logins.Keys() {
			held := object(kept.Dict(name).Get(key))
			kept.Dict(name).Set(key, held)
			for _, meter := range objects(logins.Dict(key).Get("meters")) {
				ends, dated := number(meter.Get("resets_at"))
				if title, named := meter.Get("name").(string); dated && named && !session(meter) {
					held.Set(title, lastTwo(held.Get(title), ends))
				}
			}
		}
	}
	return kept
}

// lastTwo is the latest two of the window ends listed and end, each once, earliest first.
func lastTwo(listed any, end float64) []any {
	ends := map[float64]any{}
	var at []float64
	items, _ := listed.([]any)
	for _, each := range append(slices.Clone(items), run.Float(end)) {
		if value, ok := number(each); ok && ends[value] == nil {
			ends[value], at = each, append(at, value)
		}
	}
	slices.Sort(at)
	var latest []any
	for _, value := range at[max(0, len(at)-2):] {
		latest = append(latest, ends[value])
	}
	return latest
}
