package config

import "slices"

// EntryNames is the name of each [models.*] table, in file order, as Python's cfg["models"]
// holds them: Entries in the order a reader taking the first match goes through them.
func EntryNames() ([]string, error) {
	root, err := load()
	if err != nil {
		return nil, err
	}
	return slices.Clone(root.values["models"].(*table).keys), nil
}
