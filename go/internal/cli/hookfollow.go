package cli

import (
	"os"

	"agentkit/internal/config"
	"agentkit/internal/harness"
	"agentkit/internal/run"
	"agentkit/internal/seat"
)

// following is whether the seat goes on in the conversation its own client went to, as the hook's
// event names it (`harness.HookFollows`, Harness.follow), while the hook's caller still runs: only
// in a pane, the one place a hook can be the seat's own client's, and on a prompt only for
// somebody's words.  first runs right before the move is written (seat.Claim), where a prompt's
// turn is latched, as Python's hook latches it before its follow.  False where Go hands it over,
// with nothing written.
func following(launched string, event *run.Object, first func() bool) bool {
	if os.Getenv("TMUX") == "" || os.Getenv("TMUX_PANE") == "" ||
		event.Get("hook_event_name") == "UserPromptSubmit" && ownersWords(event) == nil {
		return true
	}
	if to := harness.HookFollows(config.SeatHarness(launched), event); to != nil {
		return seat.Claim(launched, *to, os.Getppid(), first)
	}
	return true
}
