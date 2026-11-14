package listing

import (
	"errors"
	"os"
	"os/exec"
	"path/filepath"

	"agentkit/internal/config"
	harnesses "agentkit/internal/harness"
)

// Lister is the words a harness's logins are asked their models with, `models` after them, as
// Python's config.adapter_path finds its script: $AGENTKIT_ADAPTER_DIR's, none where none runs
// there, which lists nothing; else, for a harness with a `models` verb of its own, this program's
// `ak adapter`, as adapters.SignIn runs a login; else the checkout's script.  False where there is
// none to ask: go/adapters' stubs carry out no other harness's `models`, and a shipped script
// answers only beside the tools/catalog.py it prints the table with.
func Lister(harness string) ([]string, bool) {
	script, err := config.Adapter(harness)
	switch {
	case script != "":
		return []string{script}, true
	case !errors.Is(err, config.ErrNoAdapterDir):
		return nil, true
	case harnesses.Verb(harness, "models") != nil:
		program, _, err := config.Running()
		return []string{program, "adapter", filepath.Dir(filepath.Dir(program)), harness}, err == nil
	}
	repo := config.Repo()
	script = filepath.Join(repo, "adapters", harness+".sh")
	_, runs := exec.LookPath(script)
	_, table := os.Stat(filepath.Join(repo, "tools", "catalog.py"))
	return []string{script}, runs == nil && table == nil
}
