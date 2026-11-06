package harness

import (
	"errors"

	"agentkit/internal/config"
)

// Present is whether that harness is present to run a turn: its adapter here, a home naming no
// adapter directory having the shipped ones, and its program found, the one its `[update] version`
// runs, else the harness's own name (config.harness_present).
func Present(name string) bool {
	if _, err := config.Adapter(name); err != nil && !errors.Is(err, config.ErrNoAdapterDir) {
		return false
	}
	program := name
	if version, err := config.Words(name, "update", "version"); err == nil && len(version) > 0 && version[0] != "" {
		program = version[0]
	}
	return Binary(program) != ""
}
