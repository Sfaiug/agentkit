package config

import (
	"os"
	"path/filepath"
	"slices"
)

// TakesTests is whether the machine config.toml names takes suites: none does while MachineWork
// cannot be read, and then every suite runs here.
func TakesTests(name string) bool {
	work, known := MachineWork(name)
	return known && slices.Contains(work, "tests")
}

// MachineWork is the work config.toml marks machine `name` for, as Python's machines.work reads
// the marks before a Mac's probe rules turns out: its `[machines.<name>]` table's `work`, or for
// "" `[google_cloud]`'s, every rental's; with none, the old turns_on_machines switch's, turns
// while it is true, and tests.  False where the file cannot be read or any table's marks are some
// Python refuses (config._work_in).
func MachineWork(name string) ([]string, bool) {
	data, err := os.ReadFile(filepath.Join(Home(), "config.toml"))
	if err != nil && !os.IsNotExist(err) {
		return nil, false
	}
	root, err := parseDocument(string(data))
	if err != nil {
		return nil, false
	}
	named, _ := root.get("machines").(*table)
	tables := []any{root.get("google_cloud")}
	if named != nil {
		for _, key := range named.keys {
			tables = append(tables, named.values[key])
		}
	}
	for _, each := range tables {
		if own, ok := each.(*table); ok && own.values["work"] != nil && marks(own.values["work"]) == nil {
			return nil, false
		}
	}
	own, _ := root.get("google_cloud").(*table)
	if name != "" {
		own, _ = named.get(name).(*table)
	}
	if work := own.get("work"); work != nil {
		return marks(work), true
	}
	if root.get("turns_on_machines") == true {
		return []string{"turns", "tests"}, true
	}
	return []string{"tests"}, true
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
