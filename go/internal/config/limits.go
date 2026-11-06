package config

import (
	"fmt"
	"math/big"
	"os"
	"path/filepath"
)

// A Limit is one of the numbers a run holds to as `Limits` on `c` shows it: its key, the value in
// force and ak's default, each as a run's record keeps it, what it means and the board rows it
// moves (Python's config.POLICY beside host_policy).
type Limit struct {
	Key            string
	Value, Default any
	Meaning        string
	Moves          []string
}

// Limits is the numbers, each a Limit, in policy's order.
func (n Numbers) Limits() []Limit {
	held, given := n.limits(), defaults.limits()
	limits := make([]Limit, len(policy))
	for i, number := range policy {
		limits[i] = Limit{number.key, held[i].Said(), given[i].Said(), number.meaning, number.moves}
	}
	return limits
}

// SaveLimit writes config.toml as Python's config.save does with the number `key` set to `value`,
// a whole number or "no limit" (menu.config_limits' take): refused, naming the file and nothing
// written, where host_policy would refuse the numbers it leaves.  `keep` is as RememberDefaults's.
func SaveLimit(key string, value any, keep func() error) error {
	path := filepath.Join(Home(), "config.toml")
	data, err := os.ReadFile(path)
	if err != nil && !os.IsNotExist(err) {
		return err
	}
	file, err := parseDocument(string(data))
	if err != nil {
		return err
	}
	if number, whole := value.(int); whole {
		value = big.NewInt(int64(number))
	}
	return saveConfig(file, func(root *table) error {
		root.put(key, value)
		if _, err := policyIn(func(key string) (any, bool) {
			value, set := root.values[key]
			return value, set
		}, defaults); err != nil {
			return fmt.Errorf("%s: %w", path, err)
		}
		return nil
	}, keep)
}
