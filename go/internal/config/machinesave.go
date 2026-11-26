package config

import (
	"fmt"
	"path/filepath"
)

// Marks is the work a table of machine marks names: `[machines.<Machine>]`.
type Marks struct {
	Machine string
	Work    []string
}

// SaveMachine writes config.toml as Python's config.save does with `[machines.<name>]`'s `work`
// set to work.  `implied` and `keep` are as saveMarks's.
func SaveMachine(name string, work []string, implied []Marks, keep func() error) error {
	return saveMarks(name, func(own *table) { own.put("work", listed(work)) }, implied, keep)
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
		own, ok := root.nest([]string{"machines", name}, false)
		if !ok {
			return fmt.Errorf("%s holds no table of marks for %q", filepath.Join(Home(), "config.toml"), name)
		}
		set(own)
		if _, switched := root.values["turns_on_machines"]; switched {
			for _, each := range implied {
				if own, ok := root.nest([]string{"machines", each.Machine}, false); ok && own.get("work") == nil {
					own.put("work", listed(each.Work))
				}
			}
			delete(root.values, "turns_on_machines")
		}
		return nil
	}, keep)
}
