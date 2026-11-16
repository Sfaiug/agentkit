package usage

import (
	"slices"

	"agentkit/internal/config"
	"agentkit/internal/run"
)

// Snapshot is the readings a usage snapshot's providers hold as of now, judged for those models:
// what the contract check reads windows off, a snapshot of its own beside the host's.
func Snapshot(providers *run.Object, models map[string]config.Model) *Readings {
	return &Readings{providers: providers, models: models, now: clock()}
}

// SpentUntil is when the window spending that model comes back, as Python's contract.spent_until
// reads it, as its reading holds it: the latest reset of an exhausted meter gating it, else its
// provider's exhausted_until; false where nothing spends it.
func (r *Readings) SpentUntil(name string) (any, bool) {
	if r.Spent(name) == "" {
		return nil, false
	}
	meters, prov := r.gating(name)
	until, latest, found := prov.Get("exhausted_until"), 0.0, false
	for _, meter := range meters {
		if at, ok := run.Num(meter.Get("resets_at")); ok && meter.Truthy("exhausted") && (!found || at > latest) {
			until, latest, found = meter.Get("resets_at"), at, true
		}
	}
	return until, true
}

// WithoutPast is that reading now, every meter whose window has rolled over left out, named name
// where nothing is left (withoutPast).
func WithoutPast(prov *run.Object, name string) *run.Object {
	return withoutPast(prov, clock(), name)
}

// unread is the rest of Python's usage.MARK, which its refusals write and Go's readings do not
// read yet: the levels the meters stood at, the meters a refusal can have come from, by which it
// parks only the models they gate, and the refusals in force beside the newest.
var unread = []string{"exhausted_used", "exhausted_meters", "exhausted_earlier"}

// Unread is whether that reading holds a refusal as Python keeps one, which Go's would judge
// otherwise.
func Unread(prov *run.Object) bool {
	return prov != nil && slices.ContainsFunc(unread, prov.Has)
}

// Parked is a provider's reading with the refusal that said `said` kept, as Python's
// contract.refused keeps one in a check's own snapshot, and until when: every mark of Python's
// dropped, and parked until the moment the refusal named, else the soonest of its windows still
// to roll over, else dryFor from now.
func Parked(prov *run.Object, said string) (*run.Object, float64) {
	now := clock()
	until := TryAgainAt(said)
	if until <= now {
		until = nextWindow(prov, now)
	}
	parked := run.NewObject()
	for _, key := range prov.Keys() {
		if !slices.Contains(mark, key) && !slices.Contains(unread, key) {
			parked.Set(key, prov.Get(key))
		}
	}
	parked.Set("exhausted_until", run.Float(until))
	return parked, until
}
