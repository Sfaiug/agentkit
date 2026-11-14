package cli

import (
	"os"

	"agentkit/internal/config"
	"agentkit/internal/harness"
	"agentkit/internal/run"
	"agentkit/internal/seat"
)

// following is the seat's move to the conversation its own client went to, as the hook's event
// names it (`harness.HookFollows`, Harness.follow), to make while the hook's caller still runs:
// only in a pane, the one place a hook can be the seat's own client's, and on a prompt only for
// somebody's words.  A prompt's turn is latched before its move, as Python's hook latches it, so a
// latch that fails moves nothing.  False where Go hands it over at once, with nothing written: a
// move its harness's follow does not carry (`harness.Moves`).  The move is false where Claim hands
// it over, having written nothing of its own.
func following(launched string, event *run.Object) (move func() bool, carried bool) {
	stay := func() bool { return true }
	if os.Getenv("TMUX") == "" || os.Getenv("TMUX_PANE") == "" ||
		event.Get("hook_event_name") == "UserPromptSubmit" && ownersWords(event) == nil {
		return stay, true
	}
	kind := config.SeatHarness(launched)
	if to := harness.HookFollows(kind, event); to != nil {
		return func() bool { return seat.Claim(launched, *to, os.Getppid()) }, true
	}
	return stay, !harness.Moves(kind, event)
}
