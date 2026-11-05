package run

import (
	"agentkit/internal/config"
	"agentkit/internal/gitcall"
)

// LaunchPolicy reads a repository's current default-branch limits from one commit,
// falling back to the host's where no default branch is known.
func LaunchPolicy(repo string) (config.Numbers, error) {
	commit := gitcall.RulesTip(repo)
	if commit == "" {
		return config.HostNumbers()
	}
	return config.ProjectNumbers(repo, func(key string) string { return gitcall.DeclaredAt(repo, commit, key) })
}
