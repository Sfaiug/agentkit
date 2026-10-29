package config

import (
	"embed"
	"fmt"
	"io/fs"
	"os"
	"path"
	"path/filepath"
)

// The adapter manifests ship inside the single binary; the test pins these copies to
// adapters/, which remains the source for both implementations.
//
//go:generate sh -c "rm -f adapters/*.toml && cp ../../../adapters/*.toml adapters/"
//go:embed adapters/*.toml
var adapters embed.FS

// SeatEnv is the variables a launch sets for its seat alone, as the manifests' `[launch]
// seat_env` declare them: nothing the seat starts may be told them, or a check would run
// to the orchestrator's rules.  $AGENTKIT_ADAPTER_DIR's manifest of a harness comes first.
func SeatEnv() ([]string, error) {
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
	var names []string
	for name, data := range manifests {
		root, err := parseDocument(string(data))
		if err != nil {
			return nil, fmt.Errorf("adapter manifest %s: %w", name, err)
		}
		launch, _ := root.values["launch"].(*table)
		if launch == nil {
			continue
		}
		listed, _ := launch.values["seat_env"].([]any)
		for _, each := range listed {
			if each, ok := each.(string); ok {
				names = append(names, each)
			}
		}
	}
	return names, nil
}
