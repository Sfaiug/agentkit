package config

import (
	"embed"
	"fmt"
	"io/fs"
	"os"
	"path"
	"path/filepath"
	"strings"
)

// The adapter manifests ship inside the single binary; the test pins these copies to
// adapters/, which remains the source for both implementations.
//
//go:generate sh -c "rm -f adapters/*.toml && cp ../../../adapters/*.toml adapters/"
//go:embed adapters/*.toml
var adapters embed.FS

// manifests is every adapter's manifest by its name, $AGENTKIT_ADAPTER_DIR's of a harness first.
func manifests() (map[string]*table, error) {
	manifests := map[string][]byte{}
	shipped, _ := fs.Glob(adapters, "adapters/*.toml")
	for _, each := range shipped {
		manifests[path.Base(each)], _ = adapters.ReadFile(each)
	}
	if dir := os.Getenv("AGENTKIT_ADAPTER_DIR"); dir != "" {
		for _, each := range Glob(Expand(dir), "*.toml") {
			data, err := os.ReadFile(each)
			if err != nil {
				return nil, fmt.Errorf("cannot read %s: %w", each, err)
			}
			manifests[filepath.Base(each)] = data
		}
	}
	found := map[string]*table{}
	for name, data := range manifests {
		root, err := parseDocument(string(data))
		if err != nil {
			return nil, fmt.Errorf("adapter manifest %s: %w", name, err)
		}
		found[strings.TrimSuffix(name, ".toml")] = root
	}
	return found, nil
}

// SeatEnv is the variables a launch sets for its seat alone, as the manifests' `[launch]
// seat_env` declare them: nothing the seat starts may be told them, or a check would run
// to the orchestrator's rules.
func SeatEnv() ([]string, error) {
	manifests, err := manifests()
	var names []string
	for _, root := range manifests {
		names = append(names, words(root, "launch", "seat_env")...)
	}
	return names, err
}

// Programs is the names a harness's process goes by, as patterns: each adapter's own name,
// the first word of its `[update] version` command (`grok` for Grok's), and its `[launch]
// programs`, what that command goes on to run (Muse's launcher execs `muse-bin-<build>`).
func Programs() ([]string, error) {
	manifests, err := manifests()
	var names []string
	for name, root := range manifests {
		names = append(names, name)
		if version := words(root, "update", "version"); len(version) > 0 {
			names = append(names, path.Base(version[0]))
		}
		names = append(names, words(root, "launch", "programs")...)
	}
	return names, err
}

// words is the strings a manifest lists under one key of one section.
func words(root *table, section, key string) (found []string) {
	if block, ok := root.values[section].(*table); ok {
		listed, _ := block.values[key].([]any)
		for _, each := range listed {
			if each, ok := each.(string); ok {
				found = append(found, each)
			}
		}
	}
	return found
}
