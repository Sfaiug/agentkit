package seat

import (
	"fmt"
	"math"
	"time"

	"agentkit/internal/run"
)

// backAt is when a seat out of usage comes back, in the reader's own time (menu.back_at): `19:20`
// today, `Fri 19:20` within the week, `23 Oct` past it; "" for no moment.
func backAt(when any, now time.Time) string {
	at, ok := run.Num(when)
	if !ok || math.IsNaN(at) || math.IsInf(at, 0) {
		return ""
	}
	local := time.Unix(int64(math.Floor(at)), 0)
	switch {
	case at-seconds(now) > 6*86400:
		return fmt.Sprintf("%d %s", local.Day(), local.Format("Jan"))
	case local.YearDay() == now.YearDay() && local.Year() == now.Year():
		return local.Format("15:04")
	}
	return local.Format("Mon 15:04")
}
