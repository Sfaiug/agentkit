package config

import (
	"fmt"
	"math/big"
	"os"
	"path/filepath"
)

// machineTable parses config.toml and validates every machine table (workIn), refusing, as
// Python's machines.work does, a file that cannot be read or any table refused.
func machineTable() (*table, error) {
	path := filepath.Join(Home(), "config.toml")
	data, err := os.ReadFile(path)
	if err != nil && !os.IsNotExist(err) {
		return nil, fmt.Errorf("cannot read %s: %w", path, err)
	}
	root, err := parseDocument(string(data))
	if err == nil {
		err = workIn(root)
	}
	if err != nil {
		return nil, fmt.Errorf("%s: %w", path, err)
	}
	return root, nil
}

// MachineWork is the work config.toml marks machine `name` for, as Python's machines.work reads
// the marks before a Mac's probe rules turns out: its `[machines.<name>]` table's `work`; with
// none, the old turns_on_machines switch's, turns while it is true, and tests.  Refused where the
// file cannot be read or any table's marks or cap are some Python refuses (config._work_in).
func MachineWork(name string) ([]string, error) {
	root, err := machineTable()
	if err != nil {
		return nil, err
	}
	named, _ := root.get("machines").(*table)
	own, _ := named.get(name).(*table)
	if work := own.get("work"); work != nil {
		return marks(work), nil
	}
	if root.get("turns_on_machines") == true {
		return []string{"turns", "tests"}, nil
	}
	return []string{"tests"}, nil
}

// MachineMaxRuns is machine `name`'s `[machines.<name>] max_runs` cap as decimal digits, "" where
// none is set, as Python's machines.max_runs reads it; false where config.toml cannot be read or
// any machine table is refused (config._work_in).
func MachineMaxRuns(name string) (string, bool) {
	root, err := machineTable()
	if err != nil {
		return "", false
	}
	named, _ := root.get("machines").(*table)
	own, _ := named.get(name).(*table)
	if cap := own.get("max_runs"); cap != nil {
		return capOf(cap), true
	}
	return "", true
}

// capOf is a positive whole number as decimal digits, "" otherwise.
func capOf(value any) string {
	whole, ok := value.(*big.Int)
	if !ok || whole.Sign() < 1 {
		return ""
	}
	return whole.String()
}

// marks is a `work` value's words, nil where it is not a list of only turns and tests.
func marks(value any) []string {
	list, ok := value.([]any)
	if !ok {
		return nil
	}
	words := []string{}
	for _, word := range list {
		if word != "turns" && word != "tests" {
			return nil
		}
		words = append(words, word.(string))
	}
	return words
}
