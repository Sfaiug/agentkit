package seat

import (
	"os"
	"path/filepath"

	"agentkit/internal/config"
)

// Ensure opens a fresh named seat with its caller's roles and project, remembering no defaults.
// Saved conversations still use the ordinary reopen path.
func Ensure(name string, roles config.Selection, repo string) (bool, error) {
	models, err := config.Models()
	if err != nil {
		return true, err
	}
	cwd := filepath.Join(config.UserHome(), "code")
	if err := os.MkdirAll(cwd, 0o777); err != nil {
		return true, err
	}
	return open(name, roles.Orchestrator, models[roles.Orchestrator], roles.Workers, cwd, false, repo, false, roles.Reviewers)
}
