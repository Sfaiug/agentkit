package loop

import (
	"cmp"
	"context"
	"errors"
	"math"
	"os"
	"path/filepath"

	"agentkit/internal/config"
	"agentkit/internal/host"
	"agentkit/internal/lock"
	"agentkit/internal/run"
)

// overflowed prices a pass of the suite whose cost is kept at path, Python's
// _SuiteMeasure.overflowed: where this process's cgroup ran out of memory more often than the ooms
// it had as the pass began, the suite costs at least twice the planned memory per piece, however its
// pieces ended.  Held memory stops at the cap, so no peak shows the overflow, and its next pass is
// cut smaller.  Go measures no peak yet, so the cost is twice the plan.  The cost's other fields are
// kept, merged under the state lock; a cost Go cannot write back is Python's before anything is
// written, and one that cannot be saved keeps what it held, as to Python.  A driver stopped, ctx's
// end, waits for no lock: its error is the stop's.
func overflowed(ctx context.Context, path string, ooms int, planned float64) error {
	if host.MemoryEvent("oom") <= ooms || config.EnsureDirs() != nil {
		return nil
	}
	held, err := lock.Wait(ctx, filepath.Join(config.Home(), "state", "watch.lock"))
	if err != nil {
		return context.Cause(ctx)
	}
	defer held.Close()
	cost, err := run.ReadJSON(path)
	if errors.Is(err, run.ErrLoneSurrogate) {
		return notYet("the suite's cost "+path+" holds what Go cannot write back", "pricing its overflowed pass")
	}
	cost = cmp.Or(cost, run.NewObject())
	if planned == math.Trunc(planned) && planned < 1<<52 {
		// a whole plan is Python's int: the first estimate, or what an overflow priced
		cost.Set("mem_mb", int(2*planned))
	} else {
		cost.Set("mem_mb", 2*planned)
	}
	saved, err := os.CreateTemp(filepath.Dir(path), "tmp")
	if err != nil {
		return nil
	}
	_, err = saved.WriteString(run.Line(cost))
	if closed := saved.Close(); err != nil || closed != nil || os.Rename(saved.Name(), path) != nil {
		os.Remove(saved.Name())
	}
	return nil
}
