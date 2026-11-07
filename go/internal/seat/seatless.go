package seat

import (
	"agentkit/internal/agent"
	"agentkit/internal/tmux"
)

// seatless is whether no seat tmux holds goes by that name, Python's orch.seatless of a seat with
// no record, asked of that one session afresh, since a listing a failed probe left empty proves
// nothing: the person's default server has no session by it, and ak's own has none, or one without
// ak's mark that no agent runs in.
func seatless(name string) bool {
	if !tmux.Absent(tmux.Default, "="+name) {
		return false
	}
	if tmux.Absent(tmux.Own(), "="+name) {
		return true
	}
	mark, err := tmux.Ask(tmux.Own(), "display-message", "-p", "-t", "="+name+":", "#{"+tmux.Mark+"}")
	return err == nil && mark != "1" && agent.Agentless(tmux.Own(), []string{name})
}
