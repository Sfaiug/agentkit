package run

import "agentkit/internal/config"

// MemoryCapMB is one run's memory cap in MiB below a slice ceiling of ceiling MiB, as Python's
// run.memory_cap_mb: the config's run_memory_max_mb where set, else 40% of the ceiling, so a
// leak dies inside its own scope and a larger machine's runs grow with it; 4 GB where there is
// no ceiling.
func MemoryCapMB(ceiling int) (int, error) {
	if configured, set, err := config.RunMemoryMaxMB(); set || err != nil {
		return configured, err
	}
	if ceiling <= 0 {
		return 4096, nil
	}
	return max(1, ceiling*40/100), nil
}
