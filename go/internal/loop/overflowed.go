package loop

import (
	"context"
	"math"

	"agentkit/internal/host"
	"agentkit/internal/run"
)

// overflowed prices a pass of the suite whose cost is kept at path, Python's
// _SuiteMeasure.overflowed: where this process's cgroup ran out of memory more often than the ooms
// it had as the pass began, the suite costs at least twice the planned memory per piece, or the
// memory per piece its pass kept where that is more (measure), however its pieces ended.  Held
// memory stops at the cap, so no peak shows the overflow, and its next pass is cut smaller.  The
// cost is written as costed writes it.
func overflowed(ctx context.Context, path string, ooms int, planned, kept float64) error {
	if host.MemoryEvent("oom") <= ooms {
		return nil
	}
	return costed(ctx, path, "pricing its overflowed pass", func(cost *run.Object) {
		switch {
		case kept > 2*planned:
			cost.Set("mem_mb", kept)
		case planned == math.Trunc(planned) && planned < 1<<52:
			// a whole plan is Python's int: the first estimate, or what an overflow priced
			cost.Set("mem_mb", int(2*planned))
		default:
			cost.Set("mem_mb", 2*planned)
		}
	})
}
