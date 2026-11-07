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

// tight is MemoryTight on these readings: a wait gate._wait_reason gives with no load gate.
func (r Readings) tight(peak func() (float64, bool, error)) (bool, error) {
	total, _ := r.Number("mem_total_mb", "total_mb", "mem_total")
	minimum, err := config.MinFreeMB(total)
	if err != nil {
		return false, err
	}
	reason, _, err := r.wait(minimum, 0, peak, 0, Starting{})
	return reason != "", err
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
