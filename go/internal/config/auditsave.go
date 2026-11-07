package config

import "fmt"

// SaveAudit writes config.toml as Python's config.save does with `[audit]`'s `key` set to `value`
// (saveSetting), refused where Audit cannot read what it leaves.
func SaveAudit(key string, value any, keep func() error) error {
	return saveSetting("audit", key, value, func(root *table) error {
		_, _, err := audit(root)
		return err
	}, keep)
}

// saveSetting writes config.toml as Python's config.save does with `[name]`'s `key` set to
// `value`, a list of names as one, or taken out for nil, beside the keys the table holds
// (menu.setting's write): refused, nothing written, where `read` cannot read what it leaves.  The
// file's own [defaults] are written as it has them.  `keep` is as RememberDefaults's.
func saveSetting(name, key string, value any, read func(*table) error, keep func() error) error {
	if names, ok := value.([]string); ok {
		value = listed(names)
	}
	return saveConfig(fileTable, func(root *table) error {
		held, ok := root.nest([]string{name}, false)
		if !ok {
			return fmt.Errorf("~/.agentkit/config.toml: [%s] must be a table", name)
		}
		if value == nil {
			delete(held.values, key)
		} else {
			held.put(key, value)
		}
		// read as `read` reads it, over the defaults load() fills in where the file leaves them out
		effective, err := load()
		if err != nil {
			return err
		}
		effective.put(name, held)
		return read(effective)
	}, keep)
}
