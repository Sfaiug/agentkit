package listing

import (
	"errors"
	"path/filepath"

	"agentkit/internal/config"
	harnesses "agentkit/internal/harness"
)

// Lister is the words a harness's logins are asked their models with, `models` after them, as
// Python's config.adapter_path finds its script: $AGENTKIT_ADAPTER_DIR's, none where none runs
// there, which lists nothing; else this program's `ak adapter`, as adapters.SignIn runs a login.
// False where there is none to ask: a harness with no `models` verb of its own ships no adapter.
func Lister(harness string) ([]string, bool) {
	script, err := config.Adapter(harness)
	switch {
	case script != "":
		return []string{script}, true
	case !errors.Is(err, config.ErrNoAdapterDir):
		return nil, true
	case harnesses.Verb(harness, "models") == nil:
		return nil, false
	}
	program, _, err := config.Running()
	return []string{program, "adapter", filepath.Dir(filepath.Dir(program)), harness}, err == nil
}
