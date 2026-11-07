package config

import (
	"context"
	"os"
	"path/filepath"
	"slices"

	"agentkit/internal/lock"
)

// saveConfig shares c's whole-file rewrite and record preparation with other menu edits, read
// reading the file whose own keys go over the config, all under editing's lock.
func saveConfig(read func() (*table, error), change func(*table) error, keep func() error) error {
	held, err := editing()
	if err != nil {
		return err
	}
	defer held.Close()
	file, err := read()
	if err != nil {
		return err
	}
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

// editing holds ~/.agentkit's directory flock, Python's policy migration's, which survives
// replacing config.toml: one read, change and replace of the file, through the config.tmp every
// writer shares, at a time.  The home is made first, as Python's save makes it: a missing path
// would be locked as a new file.
func editing() (*os.File, error) {
	if err := os.MkdirAll(Home(), 0o700); err != nil {
		return nil, err
	}
	return lock.Wait(context.Background(), Home())
}

// fileTable is config.toml as its own keys stand, none for no file.
func fileTable() (*table, error) {
	data, err := os.ReadFile(filepath.Join(Home(), "config.toml"))
	if err != nil && !os.IsNotExist(err) {
		return nil, err
	}
	return parseDocument(string(data))
}

// modelTable is modelFile's table, what c's model edits write over the config.
func modelTable() (*table, error) {
	_, file, err := modelFile()
	return file, err
}
