package host

import (
	"fmt"
	"os"
	"os/exec"
	"slices"
	"strings"

	"agentkit/internal/config"
)

// Serving is the command of work that serves runs of every version, a line's lander and a
// project's live follower, Python's installed_ak: the installed ak with args, ~/.local/bin/ak where
// that is a file, else this program.  The owner, 5 Nov 2026: a fix to it takes effect once it is
// installed, and members launched on different versions stack.  The installed ak may be one that
// cannot say it started where it was placed.  It serves no one run: its environment is Apart's at
// depth 0.
func Serving(args ...string) (*exec.Cmd, error) {
	env, err := Apart(0)
	if err != nil {
		return nil, err
	}
	var cmd *exec.Cmd
	installed := config.UnderHome(".local", "bin", "ak")
	if found, err := os.Stat(installed); err == nil && found.Mode().IsRegular() {
		cmd = Witnessed(installed, args...)
	} else {
		self, err := os.Executable()
		if err != nil {
			return nil, err
		}
		cmd = exec.Command(self, args...)
	}
	cmd.Env = env
	return cmd, nil
}

// Apart is the child environment, at run depth depth, of work that outlives its caller, a lander or
// the next delivery a driver wakes: none of a run's, job's or seat's own variables, so it belongs
// to no caller's stop sweep.
func Apart(depth int) ([]string, error) {
	env, err := config.ChildEnv()
	if err != nil {
		return nil, err
	}
	env = slices.DeleteFunc(env, func(pair string) bool {
		key, _, _ := strings.Cut(pair, "=")
		return slices.Contains([]string{Marker, "AK_PARENT_RUN", "AK_RUN_LOG", "AK_RUN_ROLE", "AK_RUN_DEPTH",
			"AGENTKIT_JOB_DIR", "AGENTKIT_SESSION", "AGENTKIT_UNATTENDED"}, key)
	})
	return append(env, fmt.Sprintf("AK_RUN_DEPTH=%d", depth)), nil
}
