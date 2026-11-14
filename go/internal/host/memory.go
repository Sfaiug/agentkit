package host

import (
	"math"
	"os"
	"strconv"
	"strings"
)

// memoryPressureLimit is the share of the time ak's slice may stall on memory before a run
// waits (gate.MEMORY_PRESSURE_LIMIT).
const memoryPressureLimit = 10

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
