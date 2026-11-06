package tmux

import (
	"errors"
	"os/exec"
	"strings"
)

// Absent is whether no session by that target is on the server, on tmux's own word
// (orch.session_absent): it cannot find one, or no server runs there.  A probe that fails
// otherwise, a timeout or a refused socket, proves nothing.
func Absent(server, target string) bool {
	_, err := run(server, "has-session", "-t", target)
	said, refused := refusal(err)
	return refused && (strings.Contains(said, "can't find session:") || serverless(said))
}

// Names are the names of the sessions a server holds, Control among them, and whether it said:
// one not running holds none.
func Names(server string) ([]string, bool) {
	out, err := run(server, "list-sessions", "-F", "#{session_name}")
	if said, refused := refusal(err); refused && serverless(said) {
		return nil, true
	}
	return strings.Split(strings.TrimRight(out, "\n"), "\n"), err == nil
}

// refusal is what tmux said refusing with its exit 1.
func refusal(err error) (string, bool) {
	var refused *exec.ExitError
	if !errors.As(err, &refused) || refused.ExitCode() != 1 {
		return "", false
	}
	return string(refused.Stderr), true
}

// serverless is whether tmux's refusal says no server listens on its socket (orch.no_server).
func serverless(said string) bool {
	return strings.Contains(said, "no server running on") ||
		strings.Contains(said, "error connecting to") && strings.Contains(said, "(No such file or directory)")
}
