// Package tmux talks to tmux for ak: which server a call goes to, and what tmux answers.
package tmux

import (
	"context"
	"os"
	"os/exec"
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

// A Session is one tmux session: its name, its Mark (empty where it has none), the directory
// it started in and when, in seconds since the epoch.
type Session struct {
	Name, Mark, Path string
	Created          int64
}

// Sessions are the sessions one server holds, Control aside. A server not running, no tmux,
// or one not answering holds none; asking starts no server.
func Sessions(server string) []Session {
	out, err := run(server, "list-sessions", "-F", "#{session_name}\t#{session_path}\t#{session_created}\t#{"+Mark+"}")
	if err != nil {
		return nil
	}
	var found []Session
	for _, line := range strings.Split(strings.TrimRight(out, "\n"), "\n") {
		if parts := strings.Split(line, "\t"); len(parts) == 4 && parts[0] != Control {
			created, err := strconv.ParseInt(parts[2], 10, 64)
			if err != nil {
				created = time.Now().Unix()
			}
			found = append(found, Session{parts[0], parts[3], parts[1], created})
		}
	}
	return found
}

// Dead are the sessions on that server whose panes have all exited, which tmux still holds.
func Dead(server string) map[string]bool {
	dead, alive := map[string]bool{}, map[string]bool{}
	out, err := run(server, "list-panes", "-a", "-F", "#{session_name}\t#{pane_dead}")
	if err != nil {
		return dead
	}
	for _, line := range strings.Split(strings.TrimRight(out, "\n"), "\n") {
		if name, flag, _ := strings.Cut(line, "\t"); flag == "1" {
			dead[name] = !alive[name]
		} else {
			alive[name], dead[name] = true, false
		}
	}
	return dead
}

// Term is the TERM tmux is run with where this box has no terminfo for the one in the
// environment, and "" where it has: tmux refuses a terminal it cannot describe.
func Term() string {
	term := os.Getenv("TERM")
	if term == "" || term == "xterm-256color" || exec.Command("infocmp", term).Run() == nil {
		return ""
	}
	return "xterm-256color"
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
