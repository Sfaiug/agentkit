package host

import "fmt"

// Strain is why these readings hold even a run stalled first in line, and the gate's kind, ""
// while the host is calm, Python's gate._strain: the free memory a run needs (minimum), or ak's
// slice stalling on memory, the kernel's own reading.
func (r Readings) Strain(minimum float64) (string, string) {
	if reason, kind := r.short(minimum, Starting{}); reason != "" {
		return reason, kind
	}
	return r.pressed()
}

// short is the wait for free memory under the minimum, less what starting runs may still take,
// Python's gate._free_reason.
func (r Readings) short(minimum float64, starting Starting) (string, string) {
	if free, ok := r.Number("free_mb", "mem_available_mb", "mem_available"); minimum != 0 && ok && free-starting.MB < minimum {
		return fmt.Sprintf("waiting for memory · %s G free%s, needs %s G", G(free, true), starting.still(), G(minimum, true)), "memory"
	}
	return "", ""
}

// pressed is the wait for ak's slice stalling on memory past the limit, Python's
// gate._memory_pressure_reason.
func (r Readings) pressed() (string, string) {
	if pressure, ok := r.Number("slice_memory_pressure"); ok && pressure > memoryPressureLimit {
		ours, _ := r.sliceOrUnitMemory()
		return fmt.Sprintf("waiting for ak's memory · pressure %s%%, limit %d%%%s", Short(pressure), memoryPressureLimit, ours.inSwap()), "unit memory"
	}
	return "", ""
}
