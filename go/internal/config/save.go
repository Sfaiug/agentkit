package config

import (
	"os"
	"path/filepath"
	"slices"
)

// saveConfig shares c's whole-file rewrite and record preparation with other menu edits.
func saveConfig(file *table, change func(*table) error, keep func() error) error {
	root, err := load()
	if err != nil {
		return err
	}
	// what Python's load() does beside validate: [tiers] gone, its pace_margin kept where the
	// file has none, and the provider of a harness that hosts providers named by its label
	if tiers, ok := root.get("tiers").(*table); ok && root.get("pace_margin") == nil && tiers.get("pace_margin") != nil {
		root.put("pace_margin", tiers.get("pace_margin"))
	}
	delete(root.values, "tiers")
	hosts, err := manifests()
	if err != nil {
		return err
	}
	for harness, manifest := range hosts {
		block, _ := manifest.get("providers").(*table)
		label, named := block.get("label").(string)
		if entry, ok := root.get("providers").(*table).get(harness).(*table); ok && named {
			entry.put("name", label)
		}
	}
	for _, key := range present(file) {
		if !slices.Contains([]string{"tiers", "models", "providers"}, key) {
			root.put(key, file.values[key])
		}
	}
	if err := change(root); err != nil {
		return err
	}
	text, err := dump(root)
	if err != nil {
		return err
	}
	tmp := filepath.Join(Home(), "config.tmp")
	if err := os.WriteFile(tmp, []byte(text), 0o600); err != nil {
		return err
	}
	defer os.Remove(tmp)
	if err := os.Chmod(tmp, 0o600); err != nil {
		return err
	}
	if err := keep(); err != nil {
		return err
	}
	return os.Rename(tmp, filepath.Join(Home(), "config.toml"))
}
