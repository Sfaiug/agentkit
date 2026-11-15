package seat

import (
	"slices"

	"agentkit/internal/run"
)

// spentRuns is whether a run waits for its window to refill, whose squares are Python's to draw in
// out of usage's colour.  Read before filing writes, so such a frame is left before anything is
// written.
func spentRuns(runs map[string][]ran) bool {
	for _, mine := range runs {
		if slices.ContainsFunc(mine, func(each ran) bool { return run.ExhaustedWait(each.record) == "window" }) {
			return true
		}
	}
	return false
}
