package usage

import "agentkit/internal/run"

// ModelSpent is whether that model has nothing left to spend at all, and why, Python's
// usage.model_spent, which the orchestrator's choice asks: a meter gating it spent until a reset
// still ahead, with no credits left; the used side alone, as being ahead of pace is no reason to
// pass over the seat its owner works from.
func (r *Readings) ModelSpent(name string) (bool, string) {
	meters, prov := r.gating(name)
	var spent, worst *run.Object
	for _, meter := range meters {
		flag := "exhausted"
		if meter.Has("tier_a_exhausted") {
			flag = "tier_a_exhausted"
		}
		if meter.Truthy(flag) && (spent == nil || used(meter) > used(spent)) {
			spent = meter
		}
		if worst == nil || used(meter) > used(worst) {
			worst = meter
		}
	}
	said := func(meter *run.Object) string {
		return text(meter.Get("name")) + " " + text(meter.Get("used")) + "% used"
	}
	switch left := creditsNote(prov); {
	case spent != nil && left != "":
		return false, said(spent) + ", " + left
	case spent != nil:
		return true, said(spent) + " >= 100"
	case worst == nil:
		label := r.models[name].Meter
		if label == "" {
			label = "provider meters"
		}
		return false, label + " (not reported)"
	}
	return false, said(worst) + " < 100"
}
