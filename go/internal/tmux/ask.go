package tmux

import "strings"

// Ask is what one server answers a command, stripped as Python's orch.tmux_out strips it; an
// error where tmux refused, is missing or never answered.
func Ask(server string, args ...string) (string, error) {
	out, err := run(server, args...)
	return strings.TrimSpace(out), err
}
