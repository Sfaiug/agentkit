package seat

import (
	"agentkit/internal/agent"
	"agentkit/internal/tmux"
)

// seatless is whether no seat tmux holds goes by that name, Python's orch.seatless of a seat with
// no record: orch.find does not find one, and ak's own server, asked afresh, has no session by it,
// or one no agent runs in.  A probe that fails proves neither.
func seatless(name string) bool {
	held, _, known := find(name, nil)
	return known && !held && (tmux.Absent(tmux.Own(), "="+name) || agent.Agentless(tmux.Own(), []string{name}))
}
