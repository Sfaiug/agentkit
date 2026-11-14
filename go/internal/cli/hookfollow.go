package cli

import (
	"os"

	"agentkit/internal/config"
	"agentkit/internal/harness"
	"agentkit/internal/run"
	"agentkit/internal/seat"
)

// followed is the seat going on in the conversation its own client went to, as the hook's event
// names it (`harness.HookFollows`, Harness.follow), while the hook's caller still runs: only in a
// pane, the one place a hook can be the seat's own client's.  False where Go hands it over, with
// nothing written: a move Follows does not carry (`harness.Moves`) among them.
func followed(launched string, event *run.Object) bool {
	if os.Getenv("TMUX") == "" || os.Getenv("TMUX_PANE") == "" {
		return true
	}
	kind := config.SeatHarness(launched)
	if to := harness.HookFollows(kind, event); to != nil {
		return seat.Claim(launched, *to, os.Getppid())
	}
	return !harness.Moves(kind, event)
}
