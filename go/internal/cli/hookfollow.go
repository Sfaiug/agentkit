package cli

import (
	"os"

	"agentkit/internal/harness"
	"agentkit/internal/run"
	"agentkit/internal/seat"
)

// followed is the seat going on in the conversation its own client went to, as the hook's event
// names it (`harness.Follows`, Harness.follow), while the hook's caller still runs: only in a
// pane, the one place a hook can be the seat's own client's.  False where Go hands it over, with
// nothing written.
func followed(launched string, event *run.Object) bool {
	to := harness.Follows(event)
	if to == nil || os.Getenv("TMUX") == "" || os.Getenv("TMUX_PANE") == "" {
		return true
	}
	return seat.Claim(launched, *to, os.Getppid())
}
