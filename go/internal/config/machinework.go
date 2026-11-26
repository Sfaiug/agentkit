package config

import (
	"math/big"
	"os"
	"path/filepath"
)

// machineTable parses config.toml and validates every machine table (workIn); nil, false where
// the file cannot be read or any table is refused.
func machineTable() (*table, bool) {
	data, err := os.ReadFile(filepath.Join(Home(), "config.toml"))
	if err != nil && !os.IsNotExist(err) {
		return nil, false
	}
	root, err := parseDocument(string(data))
	if err != nil || workIn(root) != nil {
		return nil, false
	}
	return root, true
}

// MachineWork is the work config.toml marks machine `name` for, as Python's machines.work reads
// the marks before a Mac's probe rules turns out: its `[machines.<name>]` table's `work`; with
// none, the old turns_on_machines switch's, turns while it is true, and tests.  False where the
// file cannot be read or any table's marks or cap are some Python refuses (config._work_in).
func MachineWork(name string) ([]string, bool) {
	root, ok := machineTable()
	if !ok {
		return nil, false
	}
	named, _ := root.get("machines").(*table)
	own, _ := named.get(name).(*table)
	if work := own.get("work"); work != nil {
		return marks(work), true
	}
	if root.get("turns_on_machines") == true {
		return []string{"turns", "tests"}, true
	}
	return []string{"tests"}, true
}

// MachineMaxRuns is machine `name`'s `[machines.<name>] max_runs` cap as decimal digits, "" where
// none is set, as Python's machines.max_runs reads it; false where config.toml cannot be read or
// any machine table is refused (config._work_in).
func MachineMaxRuns(name string) (string, bool) {
	root, ok := machineTable()
	if !ok {
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
