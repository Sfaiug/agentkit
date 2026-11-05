package config

import "slices"

// TakesTests is whether the machine config.toml names takes suites, as Python's machines.work reads
// its marks: its `[machines.<name>]` table's `work` where it has one, else always.  None does while
// any table's marks are some Python refuses (config._work_in), or the file cannot be read: then
// every suite runs here.
func TakesTests(name string) bool {
	machines, _, err := topLevel("machines")
	if err != nil {
		return false
	}
	rented, _, err := topLevel("google_cloud")
	if err != nil {
		return false
	}
	named, _ := machines.(*table)
	tables := []any{rented}
	if named != nil {
		for _, key := range named.keys {
			tables = append(tables, named.values[key])
		}
	}
	for _, each := range tables {
		if own, ok := each.(*table); ok && own.values["work"] != nil && marks(own.values["work"]) == nil {
			return false
		}
	}
	own, _ := named.get(name).(*table)
	return own.get("work") == nil || slices.Contains(marks(own.get("work")), "tests")
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
