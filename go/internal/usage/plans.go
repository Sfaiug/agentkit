package usage

import "agentkit/internal/run"

// A Plan is a login's plan as Python's spend.weeks fits it: its name as state/logins.json names it
// now, "" for none, and the points every login of its provider rose on it and the listed dollars
// that bought them, 0 and 0 where none of its weeks counts.
type Plan struct {
	Name            string
	Points, Dollars float64
}

// Week is what a week of the plan holds in listed dollars, 100 times its dollars over its points;
// false where either is 0.
func (p Plan) Week() (float64, bool) {
	if p.Points == 0 || p.Dollars == 0 {
		return 0, false
	}
	return 100 * p.Dollars / p.Points, true
}

// show sets the plan on a login's reading as `ak usage --json` prints it, null for no name or no
// week.
func (p Plan) show(prov *run.Object) {
	prov.Set("plan", nil)
	if p.Name != "" {
		prov.Set("plan", p.Name)
	}
	prov.Set("week_listed_usd", nil)
	if week, held := p.Week(); held {
		prov.Set("week_listed_usd", week)
	}
	prov.Set("plan_points", p.Points)
	prov.Set("plan_listed_usd", p.Dollars)
}
