package config

import "fmt"

// SaveAudit writes config.toml as Python's config.save does with `[audit]`'s `key` set to `value`,
// a list of names as one, beside the keys the table holds (menu.setting's write): refused, nothing
// written, where Audit cannot read what it leaves.  The file's own [defaults] are written as it
// has them.  `keep` is as RememberDefaults's.
func SaveAudit(key string, value any, keep func() error) error {
	if names, ok := value.([]string); ok {
		value = listed(names)
	}
	return saveConfig(fileTable, func(root *table) error {
		held, ok := root.nest([]string{"audit"}, false)
		if !ok {
			return fmt.Errorf("~/.agentkit/config.toml: [audit] must be a table")
		}
		held.put(key, value)
		// read as Audit reads it, over the defaults load() fills in where the file leaves them out
		effective, err := load()
		if err != nil {
			return err
		}
		effective.put("audit", held)
		_, _, err = audit(effective)
		return err
	}, keep)
}
