package tmux

import (
	"slices"
	"strings"

	"agentkit/internal/config"
)

// Dead are the sessions on one server whose panes have all exited but which tmux still holds
// (orch.dead), Control aside.  A server not running or not answering holds none.
func Dead(server string) []string {
	out, err := run(server, "list-panes", "-a", "-F", "#{session_name}\t#{pane_dead}")
	if err != nil {
		return nil
	}
	var alive, gone []string
	for _, line := range strings.Split(strings.TrimRight(out, "\n"), "\n") {
		name, flag, _ := strings.Cut(line, "\t")
		if flag == "1" {
			gone = append(gone, name)
		} else {
			alive = append(alive, name)
		}
	}
	return slices.DeleteFunc(gone, func(name string) bool { return name == config.Control || slices.Contains(alive, name) })
}
