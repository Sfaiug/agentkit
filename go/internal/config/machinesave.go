package config

import (
	"fmt"
	"path/filepath"
)

// Marks is the work a table of machine marks names: `[machines.<Machine>]`, or `[google_cloud]`
// for "".
type Marks struct {
	Machine string
	Work    []string
}

// SaveMachine writes config.toml as Python's config.save does with `key` of a table of machine
// marks set to `value`: `[machines.<name>]`'s `work`, or for "" `[google_cloud]`'s, which holds
// the cloud's `active` and `max_month` too.  `implied` and `keep` are as saveMarks's.
func SaveMachine(name, key string, value any, implied []Marks, keep func() error) error {
	if work, ok := value.([]string); ok {
		value = listed(work)
	}
	return saveMarks(name, func(own *table) { own.put(key, value) }, implied, keep)
}

// AddMachine writes config.toml as Python's config.save does with `[machines.<name>]` added,
// nothing in it: a machine ak may use, its marks the defaults.
func AddMachine(name string, implied []Marks, keep func() error) error {
	return saveMarks(name, func(*table) {}, implied, keep)
}

// saveMarks writes config.toml with the table of name's marks, made where missing, changed by set.
// Where the file still holds the old turns_on_machines switch, save writes each of `implied`, the
// work it implied, in that table unless it names its own, and the switch goes.  `keep` is as
// RememberDefaults's.  An error leaves the file as it was.
func saveMarks(name string, set func(own *table), implied []Marks, keep func() error) error {
	return saveConfig(fileTable, func(root *table) error {
		own, ok := marksTable(root, name)
		if !ok {
			return fmt.Errorf("%s holds no table of marks for %q", filepath.Join(Home(), "config.toml"), name)
		}
		set(own)
		if _, switched := root.values["turns_on_machines"]; switched {
			for _, each := range implied {
				if own, ok := marksTable(root, each.Machine); ok && own.get("work") == nil {
					own.put("work", listed(each.Work))
				}
			}
			delete(root.values, "turns_on_machines")
		}
		return nil
	}, keep)
}

// marksTable is the table of a machine's marks, made where it is missing; false where a value
// stands in its way.
func marksTable(root *table, name string) (*table, bool) {
	if name == "" {
		return root.nest([]string{"google_cloud"}, false)
	}
	return root.nest([]string{"machines", name}, false)
}
