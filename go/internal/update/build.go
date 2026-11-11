package update

import (
	"os"
	"path/filepath"

	"agentkit/internal/config"
)

// AgentkitVersion is ak's version as Python's update.agentkit_version says it: ~/agentkit's count
// of commits and its date, "" where that is no checkout.
func AgentkitVersion() string {
	return inCheckout(agentkitVersion)
}

// Build is ~/agentkit's commit as Python's update.agentkit_build says it, "" where that is no
// checkout: what tells one build from the next where ak keeps something per build, as two builds
// may read one version.
func Build() string {
	return inCheckout(func(env []string, checkout string) string {
		if commit, ok := git(env, checkout, "rev-parse", "HEAD"); ok {
			return commit
		}
		return ""
	})
}

// inCheckout is what say reads of ~/agentkit with git's environment, "" where neither is had.
func inCheckout(say func(env []string, checkout string) string) string {
	home, err := os.UserHomeDir()
	if err != nil {
		return ""
	}
	env, err := config.ChildEnv()
	if err != nil {
		return ""
	}
	return say(append(env, pins...), filepath.Join(home, "agentkit"))
}
