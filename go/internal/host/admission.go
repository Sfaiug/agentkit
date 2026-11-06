package host

import (
	"encoding/json"
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

// Admits is whether these readings let a run in, as Python's gate._gates_admit judges them while
// no run's peak is measured: memory as MemoryTight reads it, then, where the owner pinned the load
// gate and the run does not go first, the load under its limit with each of the frozen runs
// holding a slot counted 1 against it.
func Admits(readings Readings, first bool, frozen func() int) (bool, error) {
	cpus, _ := readings.Number("cpus", "nproc")
	maximum, err := config.MaxLoad(cpus) // read whether pinned or not, as resource_limits reads it
	if err != nil {
		return false, err
	}
	if tight, err := readings.tight(func() (float64, bool, error) { return 0, false, nil }); tight || err != nil {
		return false, err
	}
	load, read := readings.Number("load", "load1", "load_1m")
	if first || !config.MaxLoadSet() || maximum == 0 || !read {
		return true, nil
	}
	held := 0.0
	if load <= maximum { // past the limit the load holds the run alone, and no cgroup is read
		held = float64(frozen())
	}
	return !(load+held > maximum), nil
}
