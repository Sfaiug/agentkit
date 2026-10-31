package tmux

import (
	"errors"
	"fmt"
	"os"
	"os/exec"
	"strings"
)

// InputTTY is the pane option naming the terminal its harness reads from, so ak never types in
// while the harness has input it has not read.  The pane keeps it across renames; respawning
// its harness resets it.
const InputTTY = "@ak_input_tty"

// NameInputTTY names path as the harness's terminal in the seat's pane this process runs in, on
// that pane's own server; outside a seat's pane it names nothing.  Its error is what tmux said
// refusing.
func NameInputTTY(path string) error {
	server, _, _ := strings.Cut(os.Getenv("TMUX"), ",")
	pane := os.Getenv("TMUX_PANE")
	if os.Getenv("AGENTKIT_SESSION") == "" || pane == "" || server == "" {
		return nil
	}
	_, err := run(Default, "-S", server, "set-option", "-p", "-t", pane, InputTTY, path)
	if refused, ok := err.(*exec.ExitError); ok {
		err = errors.New(strings.TrimSpace(string(refused.Stderr)))
	}
	if err != nil {
		return fmt.Errorf("cannot name the harness terminal: %w", err)
	}
	return nil
}
