package config

import (
	"maps"
	"slices"
)

// Manifests is why the adapter manifests cannot be read, nil where every one can: Python's
// config.load reads each of them once the config itself has passed, so a command refuses one
// that is not TOML before it does anything.
func Manifests() error {
	_, err := manifests()
	return err
}

// ManifestNames is each adapter manifest's harness, in name order, as Python's config.manifests
// walks them.
func ManifestNames() ([]string, error) {
	found, err := manifests()
	if err != nil {
		return nil, err
	}
	return slices.Sorted(maps.Keys(found)), nil
}
