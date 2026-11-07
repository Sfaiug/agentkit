package seat

import (
	"path/filepath"
	"slices"
	"time"

	"agentkit/internal/config"
	"agentkit/internal/run"
)

// outOfUsage is whether the frame holds something in out of usage's colour, whose way back and the
// model it could go on with are Python's to draw: a run waiting for its window to refill, or a seat
// whose panes run on waiting on its usage until a time.  Read before filing writes, so such a frame
// is left before anything is written; its look only confirms what it reads (glanced).
func (home Home) outOfUsage(runs map[string][]ran, now time.Time) bool {
	for _, mine := range runs {
		if slices.ContainsFunc(mine, func(each ran) bool { return run.ExhaustedWait(each.record) == "window" }) {
			return true
		}
	}
	state := filepath.Join(config.Home(), "state")
	return slices.ContainsFunc(home.Seats, func(seat Seat) bool {
		wait, err := usage(climbingOf(state, seat, sight{}, seconds(now)))
		return seat.live && (err != nil || wait != nil && wait.Truthy("until"))
	})
}
