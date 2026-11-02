package tmux

import (
	"errors"
	"os/exec"
	"strings"
)

// Rename gives the session by exactly that name a new one on one server; its error is what tmux
// said refusing.
func Rename(server, old, new string) error {
	_, err := run(server, "rename-session", "-t", Literal("="+old), new)
	if refused, ok := err.(*exec.ExitError); ok {
		return errors.New(strings.TrimSpace(string(refused.Stderr)))
	}
	return err
}
