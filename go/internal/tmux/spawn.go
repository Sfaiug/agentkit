package tmux

import (
	"context"
	"errors"
	"os"
	"os/exec"
	"strings"
	"syscall"

	"agentkit/internal/config"
)

// Spawn runs a command list that starts a pane on one server, from a client whose PATH is path
// unpinned (config.Unpinned): tmux gives a pane it spawns its client's PATH, over its session's.
// The server runs on ak's own config (Conf), never the owner's: one already up is given it first,
// as only the command starting one reads -f, and remain-on-exit has to hold before the pane
// exists.  Its error is what tmux said refusing.
func Spawn(server, path string, args ...string) error {
	conf, err := Conf()
	if err != nil {
		return err
	}
	Ask(server, "source-file", conf) // a server not up says so, and -f starts it on the file
	ctx, cancel := context.WithTimeout(context.Background(), ceiling)
	defer cancel()
	call := command(ctx, server, append([]string{"-f", conf, "start-server", ";"}, args...)...)
	call.Env = append(call.Env, "PATH="+config.Unpinned(path))
	_, err = call.Output()
	if refused, ok := err.(*exec.ExitError); ok {
		return errors.New(strings.TrimSpace(string(refused.Stderr)))
	}
	return err
}

// Attach hands this terminal to the session by exactly that name, tmux's client replacing this
// process so nothing stands between them; it answers only where it could not.
func Attach(server, name string) error {
	call := command(context.Background(), server, "attach-session", "-t", "="+name)
	if call.Err != nil {
		return call.Err
	}
	return syscall.Exec(call.Path, call.Args, call.Env)
}

// Term is what tmux runs as where this box has no terminfo for $TERM, which tmux refuses
// (Python's orch.fix_term): xterm-256color; "" where $TERM serves.
func Term() string {
	if term := os.Getenv("TERM"); term != "" && term != "xterm-256color" && exec.Command("infocmp", term).Run() != nil {
		return "xterm-256color"
	}
	return ""
}

// Literal is word as tmux takes it whole: it reads a `;` ending any argument as the end of a
// command, unless a backslash stands before it.
func Literal(word string) string {
	if strings.HasSuffix(word, ";") {
		return word[:len(word)-1] + `\;`
	}
	return word
}
