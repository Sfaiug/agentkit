package usage

// A Week is one login's shared week as the reading holds it: its provider, its account ("" for a
// provider's one login) and its shared week's meter, "" where it reads none.
type Week struct{ Provider, Account, Meter string }

// Weeks is each login's Week, in the reading's order, as Python's usage.plan_weeks names them.
func (r *Readings) Weeks() []Week {
	var weeks []Week
	for _, each := range r.logins() {
		week := Week{Provider: each.provider, Account: each.account}
		if shared := r.sharedWeek(each.provider, each.prov); shared != nil {
			week.Meter = shared.Str("name")
		}
		weeks = append(weeks, week)
	}
	return weeks
}
