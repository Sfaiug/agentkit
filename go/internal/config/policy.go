package config

import (
	"fmt"
	"math/big"
	"path/filepath"
)

// defaultRounds is the review rounds a change has before it goes back to its orchestrator.
const defaultRounds = 3

// Rounds is config.toml's `rounds`, Python's config.policy: its default where the file names none,
// and an error for anything but a whole number of at least 1.
func Rounds() (int, error) {
	root, err := load()
	if err != nil {
		return 0, err
	}
	value := root.get("rounds")
	if value == nil {
		return defaultRounds, nil
	}
	number, ok := value.(*big.Int)
	if !ok || number.Sign() < 1 || !number.IsInt64() {
		return 0, fmt.Errorf("%s: rounds must be a whole number of at least 1, the review rounds a change has before it goes back to its orchestrator to split or re-scope (got %v)",
			filepath.Join(Home(), "config.toml"), value)
	}
	return int(number.Int64()), nil
}
