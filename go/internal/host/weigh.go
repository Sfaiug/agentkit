package host

import (
	"fmt"
	"path"
	"slices"
	"strconv"
)

// Weigh sets the CPU weight of this process's unit for this boot only, where a run's record names
// it as scope, Python's run.own_unit with yield_cpu and deliver.landing_weight.  A delivery has
// its landing check's weight: it is the same landing, and at a run's, beside a line's check, each
// delivery crawled while every member behind it waited (one merge every 55 s in a line of 53 on
// 11 Nov 2026; 25 at the check's).  Any other step is in the kernel's idle class: a weight shares
// CPU over time and does not decide who runs next, and beside runs at RunWeight each wake of a
// check's tests stood behind a run's thread, a check taking 84 minutes beside busy runs and 43
// beside none (13 Nov 2026).  Idle is asked of the running unit, not among its start's properties:
// a manager that does not know the word (systemd before 252) refuses only it, at no WARN line, and
// the unit has a run's weight.  Each other weight not set is one WARN line said.
func Weigh(scope string, delivering bool, say func(string)) {
	relative, _ := ownCgroup()
	unit := path.Base(relative)
	if !slices.Contains(ScopeUnits(scope), unit) {
		return
	}
	switch {
	case delivering:
		setWeight(unit, strconv.Itoa(LanderWeight), say)
	case !setWeight(unit, "idle", func(string) {}):
		setWeight(unit, strconv.Itoa(RunWeight), say)
	}
}

// setWeight is whether the unit's CPU weight was set, Python's run.set_property.
func setWeight(unit, weight string, say func(string)) bool {
	code, err := setProperty(unit, "CPUWeight="+weight)
	why := fmt.Sprintf("systemctl exited %d", code)
	if err != nil {
		why = err.Error()
	}
	if err != nil || code != 0 {
		say("WARN CPUWeight on " + unit + " was not set: " + why)
		return false
	}
	return true
}
