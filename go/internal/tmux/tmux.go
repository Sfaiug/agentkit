// Package tmux talks to tmux for ak: which server a call goes to, and what tmux answers.
package tmux

import (
	"context"
	"os"
	"os/exec"
	"slices"
	"strconv"
	"strings"
	"time"
)

// Default is the person's own tmux server, where only seats from before ak had one of its own live.
const Default = ""

// Mark is the session option that says ak opened this seat.
const Mark = "@ak_orch"

// Control is Go's own hidden session on ak's server: no caller is ever shown it.
const Control = "_ak"

// tmux answers in milliseconds, so one silent this long never will.
const ceiling = 15 * time.Second

// Own is ak's own tmux server, never the person's default one; a test names its own.
func Own() string {
	if name := os.Getenv("AGENTKIT_TMUX_SOCKET"); name != "" {
		return name
	}
	return "agentkit"
}

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
		if at := strings.LastIndexByte(line, '\t'); at >= 0 && (line[:at] != Control || server != Own()) {
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

// run asks one server. $TMUX goes: inside somebody's tmux, a call to the default server
// would follow it to theirs.
func run(server string, args ...string) (string, error) {
	ctx, cancel := context.WithTimeout(context.Background(), ceiling)
	defer cancel()
	if server != Default {
		args = append([]string{"-L", server}, args...)
	}
	command := exec.CommandContext(ctx, "tmux", args...)
	command.Env = []string{}
	for _, entry := range os.Environ() {
		if !strings.HasPrefix(entry, "TMUX=") {
			command.Env = append(command.Env, entry)
		}
	}
	out, err := command.Output()
	return string(out), err
}
