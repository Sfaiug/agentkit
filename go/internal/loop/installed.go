package loop

import (
	"os"
	"os/exec"

	"agentkit/internal/config"
	"agentkit/internal/host"
)

// lander is the command of the line's lander, `ak run --lander NAME`, Python's start_line: the
// installed ak, ~/.local/bin/ak where that is a file, else this program.  The owner, 5 Nov 2026:
// a lander fix takes effect once it is installed, and members launched on different versions
// stack.  The installed ak may be one that cannot say it started where it was placed.
func lander(name string) (*exec.Cmd, error) {
	installed := config.UnderHome(".local", "bin", "ak")
	if found, err := os.Stat(installed); err == nil && found.Mode().IsRegular() {
		return host.Witnessed(installed, "run", "--lander", name), nil
	}
	self, err := os.Executable()
	if err != nil {
		return nil, err
	}
	return exec.Command(self, "run", "--lander", name), nil
}
