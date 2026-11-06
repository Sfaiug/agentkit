package run

import (
	"errors"

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

// TaskPolicy is LaunchPolicy for a task's launch, refused where executors are off: then only a
// review launches, as in Python's launch_policy.
func TaskPolicy(repo string) (config.Numbers, error) {
	numbers, err := LaunchPolicy(repo)
	if err == nil && numbers.ReviewLines == config.AtMost(0) {
		return numbers, errors.New("executor_lines = 0: " + config.ExecutorsOff)
	}
	return numbers, err
}
