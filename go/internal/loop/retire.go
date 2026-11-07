package loop

import (
	"agentkit/internal/plan"
	"agentkit/internal/run"
)

// A plan line ticking ends the runs that only repeat it through Go's one stop, which plan cannot
// import, since loop reads plans: decided as the record reads under its lock, and once decided
// carried out whatever the home reads by then.
func init() {
	plan.Ending = func(dir string, record *run.Object) func(string) {
		if !goStops(dir, record) {
			return nil
		}
		return func(why string) { end(dir, false, why, nil) }
	}
}
