package update

import (
	"os"
	"path/filepath"

	"agentkit/internal/config"
)

// Build is ak's build as Python's update.agentkit_version says it: ~/agentkit's short commit and
// its date, "" where that is no checkout.
func Build() string {
	home, err := os.UserHomeDir()
	if err != nil {
		return ""
	}
	env, err := config.ChildEnv()
	if err != nil {
		return ""
	}
	said, _ := agentkitVersion(append(env, pins...), filepath.Join(home, "agentkit"))
	return said
}
