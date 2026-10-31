//go:build unix

package adapters

import (
	"fmt"
	"io"
	"os/exec"

	"agentkit/internal/relay"
	"agentkit/internal/tmux"
)

// run runs the program on a terminal of its own, which the seat's pane names first, and stays its
// parent: what the harness shows, and its exit, pass through here.
func run(program string, words, env []string, errOut io.Writer) int {
	cmd := exec.Command(program, words[1:]...)
	cmd.Args[0], cmd.Env = words[0], env
	code, err := relay.Run(cmd, tmux.NameInputTTY)
	if err != nil {
		fmt.Fprintf(errOut, "ak adapter: %s: %s\n", words[0], err)
	}
	return code
}
