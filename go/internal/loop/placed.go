package loop

import (
	"fmt"
	"math"
	"os/exec"
	"path/filepath"
	"strings"
	"time"

	"agentkit/internal/host"
	"agentkit/internal/run"
)

// place starts cmd, the run's driver, in the run's own unit, Python's run_placement, and says on
// the record and in the log where it went: its unit and the memory cap it holds, which a cap's
// kill names after the process that knew it is gone, or none and why.  A run a unit held before,
// one its lander wakes, goes in a unit no leftover of that one holds.
func place(dir string, cmd *exec.Cmd, detached bool, record *run.Object) (int, error) {
	capMB, err := run.MemoryCapMB(host.SliceMemoryMax())
	if err != nil {
		return 0, err
	}
	unit := "agentkit-run-" + filepath.Base(dir)
	if !unitless(record) {
		if unit, err = host.FreeUnit(unit); err != nil {
			return 0, err
		}
	}
	pid, scope, reason, err := host.Place(cmd, filepath.Join(dir, "log.txt"), unit, host.Limits(capMB, host.RunWeight), detached)
	if err != nil {
		return 0, err
	}
	if scope == "none" {
		run.SetAll(record, "scope", scope, "scope_reason", reason)
		record.Delete("memory_cap_mb")
		scope = "none (" + reason + ")"
	} else {
		run.SetAll(record, "scope", scope, "scope_reason", nil, "memory_cap_mb", capMB)
	}
	appendLog(dir, stamped("scope: "+scope))
	return pid, nil
}

// land starts the line's lander (lander) into the line's log, in a unit of its own, Python's
// start_line: ahead of every run for the CPU, as every passed run waits behind its check,
// and capped at the most any member was capped at or peaked at, or one run's cap below the slice's
// ceiling, the host's memory where none is set, whichever is more: never the small scope of
// whatever started this pass.  Unlike Python's, it stops no scope of its own when it ends, and a
// service's manager stops what is left in that: either way the lander outlives the wakes it
// starts until they hand their runs to units of their own (CheckLine), and what its checks leave
// ends with their box.
func land(turn string, members []member, env []string) error {
	ceiling := host.SliceMemoryMax()
	if ceiling == 0 {
		total, _ := host.Read().Number("mem_total_mb", "total_mb", "mem_total")
		ceiling = int(total)
	}
	most := 0.0
	for _, m := range members {
		for _, key := range []string{"memory_cap_mb", "peak_rss_mb"} {
			if value, ok := m.record.Num(key); ok && value > 0 && !math.IsInf(value, 0) {
				most = max(most, value)
			}
		}
	}
	if ceiling > 0 {
		capMB, err := run.MemoryCapMB(ceiling)
		if err != nil {
			return err
		}
		most = max(most, float64(capMB))
	}
	cmd, err := lander(filepath.Base(turn))
	if err != nil {
		return err
	}
	cmd.Env = env
	unit := fmt.Sprintf("agentkit-lander-%s-%d", strings.TrimPrefix(filepath.Base(beside(turn, "")), ".merge-"), time.Now().UnixNano())
	_, _, _, err = host.Place(cmd, beside(turn, ".log"), unit, host.Limits(int(math.Ceil(most)), host.LanderWeight), true)
	return err
}
