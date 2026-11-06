package config

import "fmt"

// Entries is every [models.*] table as Python's cfg["models"] holds it, whether or not it runs:
// what usage reads which meters the entries claim from, as an entry offered no more still claims
// its own cap of its provider's meters.
func Entries() (map[string]Model, error) {
	root, err := load()
	if err != nil {
		return nil, err
	}
	entries := map[string]Model{}
	models := root.values["models"].(*table)
	for _, name := range models.keys {
		if entry, ok := models.values[name].(*table); ok {
			entries[name] = modelOf(entry)
		}
	}
	return entries, nil
}

// modelOf is what one [models.*] table says, "" for each field it does not set.
func modelOf(entry *table) Model {
	provider, _ := entry.values["provider"].(string)
	harness, _ := entry.values["harness"].(string)
	id := ""
	if value, set := entry.values["model"]; set && value != nil {
		id = fmt.Sprint(value)
	}
	efforts := map[string]string{}
	for _, key := range RoleEfforts {
		if word, ok := entry.values[key].(string); ok {
			efforts[key] = word
		}
	}
	meter, _ := entry.values["meter"].(string)
	mode, _ := entry.values["mode"].(string)
	return Model{provider, id, harness, efforts, meter, mode}
}
