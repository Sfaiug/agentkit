package host

import (
	"encoding/json"
	"fmt"
	"math"
	"os"

	"agentkit/internal/config"
)

// Injected is the readings AK_HOST_READINGS stands in with where it holds a JSON object, false
// where Read reads the live host.
func Injected() (Readings, bool) {
	var injected Readings
	text := os.Getenv("AK_HOST_READINGS")
	return injected, text != "" && json.Unmarshal([]byte(text), &injected) == nil && injected != nil
}

// Starting is what the runs let in that show nothing yet may still grow by, in MB, and how many
// may, Python's gate._starting: readings lag what a run just let in will use.
type Starting struct {
	MB   float64
	Runs int
}

// still is `, N starting runs may take M G more` while some may, else "", Python's gate._still.
func (s Starting) still() string {
	if s.Runs == 0 {
		return ""
	}
	plural := "s"
	if s.Runs == 1 {
		plural = ""
	}
	return fmt.Sprintf(", %d starting run%s may take %s G more", s.Runs, plural, G(s.MB, true))
}

// Limits is the free memory a run needs on these readings and the load it starts under, as
// Python's gate._gates_admit reads gate.resource_limits: no load limit for a run going first, nor
// where the owner pinned none.
func (r Readings) Limits(first bool) (float64, float64, error) {
	total, _ := r.Number("mem_total_mb", "total_mb", "mem_total")
	minimum, err := config.MinFreeMB(total)
	if err != nil {
		return 0, 0, err
	}
	cpus, _ := r.Number("cpus", "nproc")
	maximum, err := config.MaxLoad(cpus) // read whether pinned or not, as resource_limits reads it
	if err != nil || first || !config.MaxLoadSet() {
		maximum = 0
	}
	return minimum, maximum, err
}

// Hold is why these readings hold a run back against those limits and the gate's kind, "" where
// none does, as Python's gate._gates_admit words it before it asks about a landing suite: peak is
// the median peak of recent runs, measured false where none was, and starting what the runs let in
// may still take; frozen is how many of the runs holding a slot the host froze, asked only where a
// load limit stands and the load alone passes it.
func (r Readings) Hold(minimum, maximum, peak float64, measured bool, starting Starting, frozen func() int) (string, string) {
	held := 0
	if load, ok := r.Number("load", "load1", "load_1m"); maximum != 0 && ok && load <= maximum {
		held = frozen()
	}
	reason, kind, _ := r.wait(minimum, maximum, func() (float64, bool, error) { return peak, measured, nil }, held, starting)
	return reason, kind
}

// Unsteady is the wait of a run let in no sooner than a poll after the last one, with no run's
// peak measured, Python's `waiting for steady readings`: the free memory, and the load where the
// owner pinned its gate.
func (r Readings) Unsteady() string {
	reason := "waiting for steady readings · " + G(r.Number("free_mb", "mem_available_mb", "mem_available")) + " G free"
	if config.MaxLoadSet() {
		reason += ", load " + unknown(r.Number("load", "load1", "load_1m"))
	}
	return reason
}

// wait is Python's gate._wait_reason: why these readings hold a run and the gate's kind, "" where
// none does, against the free memory a run needs (minimum) and the load limit (maximum, 0 for
// none) with each frozen run counted 1 against it, what starting runs may still take counted
// against both memory gates.  An unreadable gate holds nothing.  peak is asked only where the
// slice's or a unit's memory is read.
func (r Readings) wait(minimum, maximum float64, peak func() (float64, bool, error), frozen int, starting Starting) (string, string, error) {
	if free, ok := r.Number("free_mb", "mem_available_mb", "mem_available"); minimum != 0 && ok && free-starting.MB < minimum {
		return fmt.Sprintf("waiting for memory · %s G free%s, needs %s G", G(free, true), starting.still(), G(minimum, true)), "memory", nil
	}
	if load, ok := r.Number("load", "load1", "load_1m"); maximum != 0 && ok && load+float64(frozen) > maximum {
		if frozen == 0 {
			return fmt.Sprintf("waiting for the host to calm · load %s, limit %s", Short(load), Short(maximum)), "load", nil
		}
		noun := "runs"
		if frozen == 1 {
			noun = "run"
		}
		return fmt.Sprintf("waiting for the host to calm · load %s + %d frozen %s, limit %s", Short(load), frozen, noun, Short(maximum)), "load", nil
	}
	if pressure, ok := r.Number("slice_memory_pressure"); ok && pressure > memoryPressureLimit {
		ours, _ := r.sliceOrUnitMemory()
		return fmt.Sprintf("waiting for ak's memory · pressure %s%%, limit %d%%%s", Short(pressure), memoryPressureLimit, ours.inSwap()), "unit memory", nil
	}
	unit, ok := r.sliceOrUnitMemory()
	if !ok {
		return "", "", nil
	}
	// the runs' swap past the slice's allowance, a quarter of its cap, takes room too
	swap, _ := r.Number("runs_memory_swap_mb")
	used := unit.used + math.Max(0, swap-math.Floor(unit.high/4))
	most, measured, err := peak()
	switch {
	case err != nil:
		return "", "", err
	case measured && unit.high-used-starting.MB < most:
		return fmt.Sprintf("waiting for the unit's memory · %s G left%s, a run needs %s G%s",
			G(unit.high-used, true), starting.still(), G(most, true), unit.inSwap()), "unit memory", nil
	case measured || used <= unit.high*.75:
		return "", "", nil
	case unit.hasRaw:
		return fmt.Sprintf("waiting for the unit's memory · %s of %s G in use (%s with cache)%s",
			G(used, true), G(unit.high, true), G(unit.raw, true), unit.inSwap()), "unit memory", nil
	}
	return fmt.Sprintf("waiting for the unit's memory · %s of %s G%s", G(used, true), G(unit.high, true), unit.inSwap()), "unit memory", nil
}

// inSwap is ` · N G in swap` for a memory holding swap, else "", Python's gate._in_swap.
func (m memory) inSwap() string {
	if m.swap == 0 {
		return ""
	}
	return " · " + G(m.swap, true) + " G in swap"
}
