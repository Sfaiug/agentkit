package matrix

import (
	"agentkit/internal/boards"
	"agentkit/internal/usage"
)

// Plans is each login's Plan over the over seconds up to now (spend.plans), at the listed prices
// of the boards as cached, Python's usage.plan_weeks.
func Plans(logins []usage.Week, now, over float64) map[usage.Week]usage.Plan {
	s := spending(boards.Cached())
	defer s.db.Close()
	return s.plans(logins, now, over)
}
