package tmux

import (
	"context"
	"errors"
	"os"
	"os/exec"
)

// Visit lends the terminal to a client, returning when the owner detaches.
func Visit(server, name string) error {
	call := command(context.Background(), server, "attach-session", "-t", "="+name)
	call.Stdin, call.Stdout, call.Stderr = os.Stdin, os.Stdout, os.Stderr
	err := call.Run()
	var exited *exec.ExitError
	if errors.As(err, &exited) {
		return nil // the menu comes back however tmux's client ended
	}
	return err
}
