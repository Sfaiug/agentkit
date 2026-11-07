package matrix

import (
	"agentkit/internal/boards"
	"agentkit/internal/run"
	"agentkit/internal/usage"
)

// Checks is each login's plan_checks as `ak usage --json` prints them, Python's usage.plan_checks:
// oldest first, a check of each of the last seven days, the 24 hours up to its until a whole
// number of days before now, on which its plan rose (plans over that day alone) and had a week in
// the seven days up to the day's start.  Each is the points it rose by against those that week
// foretold for the listed dollars that bought them, at the boards as cached: the plan's number as
// ak knew it then, against a day it had not seen.
func Checks(logins []usage.Week, now float64) map[usage.Week][]any {
	s := spending(boards.Cached())
	defer s.db.Close()
	checks := map[usage.Week][]any{}
	for days := 6; days >= 0; days-- {
		until := now - float64(days)*86400
		before := s.plans(logins, until-86400, SpentOver)
		for login, day := range s.plans(logins, until, 86400) {
			if week, held := before[login].Week(); held && day.Points != 0 {
				check := run.NewObject()
				check.Set("until", until)
				check.Set("rose", day.Points)
				check.Set("predicted", 100*day.Dollars/week)
				checks[login] = append(checks[login], check)
			}
		}
	}
	return checks
}
