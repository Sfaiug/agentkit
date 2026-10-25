package config

import (
	"fmt"
	"math"
	"math/big"
	"os"
	"path/filepath"
	"strconv"
	"strings"
)

// The host's gate settings sit at the top of the home config file and are read
// whether or not its model tables are valid, so a broken model never hides them.
func topLevel(key string) (any, string, error) {
	path := filepath.Join(Home(), "config.toml")
	data, err := os.ReadFile(path)
	if os.IsNotExist(err) {
		return nil, path, nil
	}
	if err != nil {
		return nil, path, fmt.Errorf("%s: %w", path, err)
	}
	root, err := parseDocument(string(data))
	if err != nil {
		return nil, path, fmt.Errorf("%s: %w", path, err)
	}
	return root.values[key], path, nil
}

// count is a non-negative integer setting, or -1 where the file leaves it out.
func count(key string) (int, error) {
	value, path, err := topLevel(key)
	if err != nil || value == nil {
		return -1, err
	}
	if number, ok := value.(*big.Int); ok && number.Sign() >= 0 && number.IsInt64() {
		return int(number.Int64()), nil
	}
	return 0, fmt.Errorf("%s: %s must be a non-negative integer", path, key)
}

// MaxRuns is the host's count ceiling; zero means no count cap.
func MaxRuns() (int, error) {
	if override, set := os.LookupEnv("AK_MAX_RUNS"); set {
		if !digitsOnly(override) {
			return 0, fmt.Errorf("AK_MAX_RUNS must be a non-negative integer (0 disables the cap for tests)")
		}
		value, _ := strconv.Atoi(override)
		return value, nil
	}
	value, err := count("max_runs")
	if value < 0 {
		value = 0 // the shipped default: no count cap
	}
	return value, err
}

// MaxGates is the pinned number of heavy-suite turns, or -1 where it is derived.
func MaxGates() (int, error) {
	return count("max_gates")
}

func resource(key, environment string, fallback float64) (float64, error) {
	if override, set := os.LookupEnv(environment); set {
		text := strings.TrimSpace(override)
		var value float64
		var err error
		if strings.Contains(override, ".") {
			value, err = strconv.ParseFloat(text, 64)
		} else {
			var whole int
			whole, err = strconv.Atoi(text)
			value = float64(whole)
		}
		if err != nil || math.IsInf(value, 0) || math.IsNaN(value) || value < 0 {
			return 0, fmt.Errorf("%s must be a non-negative number", environment)
		}
		return value, nil
	}
	value, path, err := topLevel(key)
	if err != nil || value == nil {
		return fallback, err
	}
	switch number := value.(type) {
	case *big.Int:
		if number.Sign() >= 0 {
			result, _ := new(big.Float).SetInt(number).Float64()
			return result, nil
		}
	case float64:
		if !math.IsInf(number, 0) && !math.IsNaN(number) && number >= 0 {
			return number, nil
		}
	}
	return 0, fmt.Errorf("%s: %s must be a non-negative number", path, key)
}

// MinFreeMB is the memory a run needs free: a fifth of RAM, and never under 3 GB.
func MinFreeMB(totalMB float64) (float64, error) {
	return resource("min_free_mb", "AK_MIN_FREE_MB", math.Max(3072, totalMB*0.20))
}

// MaxLoad is the highest one-minute load a run starts under, the processor count by default.
func MaxLoad(cpus float64) (float64, error) {
	return resource("max_load", "AK_MAX_LOAD", math.Max(1, cpus))
}

// MaxLoadSet says whether the owner pinned the load gate; unset, CPU pressure gates instead.
func MaxLoadSet() bool {
	if _, set := os.LookupEnv("AK_MAX_LOAD"); set {
		return true
	}
	value, _, err := topLevel("max_load")
	return err == nil && value != nil
}

func digitsOnly(text string) bool {
	for _, r := range text {
		if r < '0' || r > '9' {
			return false
		}
	}
	return text != ""
}
