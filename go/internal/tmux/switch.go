package tmux

import (
	"context"
	"errors"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
)

// Inside is whether this process is a client of that server, as $TMUX names its socket.
func Inside(server string) bool {
	socket, _, _ := strings.Cut(os.Getenv("TMUX"), ",")
	return socket != "" && filepath.Base(socket) == server
}

// Switch moves this process's client to the session by exactly that name; only $TMUX says which
// client that is.  Its error is what tmux said refusing.
func Switch(server, name string) error {
	ctx, cancel := context.WithTimeout(context.Background(), ceiling)
	defer cancel()
	call := command(ctx, server, "switch-client", "-t", "="+name)
	call.Env = append(call.Env, "TMUX="+os.Getenv("TMUX"))
	_, err := call.Output()
	if refused, ok := err.(*exec.ExitError); ok {
		return errors.New(strings.TrimSpace(string(refused.Stderr)))
	}
	return err
}
