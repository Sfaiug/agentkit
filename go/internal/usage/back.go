package usage

import "agentkit/internal/run"

// Back is when that model's spent windows come back, as watch.seat_account waits on them: the
// latest reset still to come of a meter gating it that reads 100% used, or of its provider's mark,
// `marked` standing for the mark where one was just made; else `otherwise`, and where that is no
// time to come either, dryFor from now.  Each as its reading holds it.
func (r *Readings) Back(name string, marked, otherwise any) any {
	meters, prov := r.gating(name)
	var ends []any
	for _, meter := range meters {
		if used(meter) >= 100 {
			ends = append(ends, meter.Get("resets_at"))
		}
	}
	if marked == nil {
		marked = prov.Get("exhausted_until")
	}
	back, latest := otherwise, r.now
	for _, end := range append(ends, marked) {
		if at, ok := run.Num(end); ok && at > latest {
			back, latest = end, at
		}
	}
	if at, ok := run.Num(back); !ok || at <= r.now {
		return run.Float(r.now + dryFor)
	}
	return back
}
