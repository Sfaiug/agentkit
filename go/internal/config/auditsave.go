package config

import (
	"fmt"
	"os"
	"path/filepath"
)

// SaveAudit writes config.toml as Python's config.save does with `[audit]`'s `key` set to `value`,
// a list of names as one, beside the keys the table holds (menu.setting's write): refused, nothing
// written, where Audit cannot read what it leaves.  `keep` is as RememberDefaults's.
func SaveAudit(key string, value any, keep func() error) error {
	data, err := os.ReadFile(filepath.Join(Home(), "config.toml"))
	if err != nil && !os.IsNotExist(err) {
		return err
	}
	file, err := parseDocument(string(data))
	if err != nil {
		return err
	}
	if names, ok := value.([]string); ok {
		value = listed(names)
	}
	return saveConfig(file, func(root *table) error {
		held, ok := root.nest([]string{"audit"}, false)
		if !ok {
			return fmt.Errorf("~/.agentkit/config.toml: [audit] must be a table")
		}
		held.put(key, value)
		_, _, err := audit(root)
		return err
	}, keep)
}
