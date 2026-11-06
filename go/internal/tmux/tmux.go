// Package tmux talks to tmux for ak: which server a call goes to, and what tmux answers.
package tmux

import (
	"context"
	"errors"
	"os"
	"os/exec"
	"slices"
	"strconv"
	"strings"
	"time"

	"agentkit/internal/config"
)

// Default is the person's own tmux server, where only seats from before ak had one of its own live.
const Default = ""

// Mark is the session option that says ak opened this seat.
const Mark = "@ak_orch"

// HarnessPane is the session option naming the pane a seat's launch created.
const HarnessPane = "@ak_harness_pane"

// tmux answers in milliseconds, so one silent this long never will.
const ceiling = 15 * time.Second

// A Session is one tmux session's name and its Mark, empty where it has none.
type Session struct{ Name, Mark string }

// Sessions are the sessions one server holds, Control aside on ak's own. A server not running,
// no tmux, or one not answering holds none; asking starts no server.
func Sessions(server string) []Session {
	out, err := run(server, "list-sessions", "-F", "#{session_name}\t#{"+Mark+"}")
	if err != nil {
		return nil
	}
	var found []Session
	for _, line := range strings.Split(strings.TrimRight(out, "\n"), "\n") {
		if at := strings.LastIndexByte(line, '\t'); at >= 0 && (line[:at] != config.Control || server != Own()) {
			found = append(found, Session{line[:at], line[at+1:]})
		}
	}
	return found
}

// Panes are the process IDs of those sessions' live panes; false where the server did not answer.
func Panes(server string, names []string) ([]int, bool) {
	out, err := run(server, "list-panes", "-a", "-F", "#{session_name}\t#{pane_pid}\t#{pane_dead}")
	if err != nil {
		return nil, false
	}
	var found []int
	for _, line := range strings.Split(out, "\n") {
		if parts := strings.Split(line, "\t"); len(parts) == 3 && parts[2] != "1" && slices.Contains(names, parts[0]) {
			if pid, err := strconv.Atoi(parts[1]); err == nil {
				found = append(found, pid)
			}
		}
	}
	return found, true
}

// Kill ends the session by exactly that name on one server; its error is what tmux said refusing.
func Kill(server, name string) error {
	_, err := run(server, "kill-session", "-t", "="+name)
	if refused, ok := err.(*exec.ExitError); ok {
		return errors.New(strings.TrimSpace(string(refused.Stderr)))
	}
	return err
}

// run asks one server.
func run(server string, args ...string) (string, error) {
	ctx, cancel := context.WithTimeout(context.Background(), ceiling)
	defer cancel()
	out, err := asked(ctx, server, args...)
	return string(out), err
}

// asked is what one call answers, asked as a UTF-8 client whatever this process's locale: tmux shows
// any other client a tab, as every format here divides its fields, and each letter past ASCII as `_`.
func asked(ctx context.Context, server string, args ...string) ([]byte, error) {
	return command(ctx, server, append(utf8(), args...)...).Output()
}

// command is one call to a server. $TMUX goes: inside somebody's tmux, a call to the default
// server would follow it to theirs. So does the mark of the ak that started this one (Python's
// owner.MARK): a server keeps its starting client's environment for good.
func command(ctx context.Context, server string, args ...string) *exec.Cmd {
	if server != Default {
		args = append([]string{"-L", server}, args...)
	}
	command := exec.CommandContext(ctx, "tmux", args...)
	command.Env = []string{}
	for _, entry := range os.Environ() {
		if !strings.HasPrefix(entry, "TMUX=") && !strings.HasPrefix(entry, "AK_OWNER=") {
			command.Env = append(command.Env, entry)
		}
	}
	return command
}
