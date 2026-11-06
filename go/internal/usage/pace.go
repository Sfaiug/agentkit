package usage

import "agentkit/internal/run"

// Pace is how far that model's meters gating it run ahead of their windows at most, false where
// none reports a pace, Python's usage.model_pace.
func (r *Readings) Pace(name string) (float64, bool) {
	meters, _ := r.gating(name)
	return run.Num(topPace(list(meters)))
}
