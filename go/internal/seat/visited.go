package seat

import (
	"strconv"
	"strings"

	"agentkit/internal/plan"
	"agentkit/internal/run"
	"agentkit/internal/tmux"
)

// visited is whether the owner has been in a done seat since its work finished, which ends its
// `done` (watch._session_state): tmux remembers even visits between looks, so it is its session's
// last attachment, later than both when its sight began and its plan's last write, with no client
// attached still.  A plan nothing can stat, which a rename moved, the next look resolves anew.
func (facts climbing) visited() bool {
	done, _ := plan.DoneAt(facts.name)
	if done.IsZero() {
		return false
	}
	began, _ := run.Num(facts.found.began)
	said, err := tmux.Ask(facts.server, "display-message", "-p", "-t", "="+facts.name+":",
		"#{session_attached}\t#{session_last_attached}")
	attached, last, _ := strings.Cut(said, "\t")
	at, unread := strconv.ParseUint(last, 10, 64)
	return err == nil && attached == "0" && unread == nil && float64(at) > max(began, seconds(done))
}
