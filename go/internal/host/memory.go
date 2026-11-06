package host

import (
	"math"
	"os"
	"strconv"
	"strings"

	"agentkit/internal/config"
)

// memoryPressureLimit is the share of the time ak's slice may stall on memory before a run
// waits (gate.MEMORY_PRESSURE_LIMIT).
const memoryPressureLimit = 10

// MemoryTight is whether memory holds a run back now, as Python's gate.memory_tight reads it:
// free memory under the floor a run needs, ak's slice stalling on it, or the slice's or unit's
// room short of what a run lately took at its peak, which peak says only where one of them is
// read, or past three quarters full where it says none.  Never under the tests' `AK_MAX_RUNS=0`.
func MemoryTight(peak func() (float64, bool, error)) (bool, error) {
	if os.Getenv("AK_MAX_RUNS") == "0" {
		return false, nil
	}
	return Read().tight(peak)
}

// tight is MemoryTight on these readings.
func (r Readings) tight(peak func() (float64, bool, error)) (bool, error) {
	total, _ := r.Number("mem_total_mb", "total_mb", "mem_total")
	minimum, err := config.MinFreeMB(total)
	if err != nil {
		return false, err
	}
	if free, ok := r.Number("free_mb", "mem_available_mb", "mem_available"); minimum > 0 && ok && free < minimum {
		return true, nil
	}
	if pressure, ok := r.Number("slice_memory_pressure"); ok && pressure > memoryPressureLimit {
		return true, nil
	}
	unit, ok := r.sliceOrUnitMemory()
	if !ok {
		return false, nil
	}
	// the runs' swap past the slice's allowance, a quarter of its cap, takes room too
	swap, _ := r.Number("runs_memory_swap_mb")
	used := unit.used + math.Max(0, swap-math.Floor(unit.high/4))
	most, measured, err := peak()
	if err != nil {
		return false, err
	}
	if measured {
		return unit.high-used < most, nil
	}
	return used > unit.high*.75, nil
}

// pressure is the larger `some` share of avg10 and avg60 in a cgroup's pressure file, false where
// it says none (host._pressure_avg): two calm ten-second readings must not hide a minute of stalls.
func pressure(path string) (float64, bool) {
	data, err := os.ReadFile(path)
	if err != nil {
		return 0, false
	}
	for _, line := range strings.Split(string(data), "\n") {
		if !strings.HasPrefix(line, "some ") {
			continue
		}
		most, found := math.Inf(-1), false
		for _, part := range strings.Fields(line) {
			name, value, _ := strings.Cut(part, "=")
			if name != "avg10" && name != "avg60" {
				continue
			}
			share, err := strconv.ParseFloat(value, 64)
			if err != nil {
				return 0, false
			}
			most, found = math.Max(most, share), true
		}
		return most, found
	}
	return 0, false
}
