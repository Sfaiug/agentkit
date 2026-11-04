package run

import (
	"agentkit/internal/config"
	"agentkit/internal/gitcall"
)

// LaunchPolicy reads a repository's current default-branch limits from one commit,
// falling back to the host's where no default branch is known.
func LaunchPolicy(repo string) (config.Numbers, error) {
	if repo == "" {
		return config.HostNumbers()
	}
	commit, err := (gitcall.Git{Repo: repo}).Try("rev-parse", "--verify", "--quiet", "refs/remotes/origin/HEAD")
	if err != nil || commit == "" {
		return config.HostNumbers()
	}
	return config.ProjectNumbers(repo, func(key string) string { return gitcall.DeclaredAt(repo, commit, key) })
}
