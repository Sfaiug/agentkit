package logins

import (
	"errors"
	"path/filepath"

	"agentkit/internal/config"
	harnesses "agentkit/internal/harness"
)

// asking is the words that ask a harness's logins when they end, `login-end` after them, as
// Python's config.adapter finds its script: $AGENTKIT_ADAPTER_DIR's; else, for a harness with a
// `login-end` of its own, this program's `ak adapter`, no script run; else the checkout's script.
func asking(harness string) ([]string, error) {
	if _, err := config.Adapter(harness); errors.Is(err, config.ErrNoAdapterDir) && harnesses.Verb(harness, "login-end") != nil {
		program, _, err := config.Running()
		return []string{program, "adapter", filepath.Dir(filepath.Dir(program)), harness}, err
	}
	adapter, err := config.LoginAdapter(harness)
	return []string{adapter}, err
}
