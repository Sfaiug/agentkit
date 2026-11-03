package cli

import (
	"agentkit/internal/notify"
	"agentkit/internal/run"
	"agentkit/internal/seat"
)

// lookAfter has the seat looked at again once its hook's event is down, a prompt in the owner's
// words handed over as what may answer its question (hooks/seat-state.sh's `look`).
func lookAfter(event *run.Object, at float64) {
	if event.Str("hook_event_name") == "UserPromptSubmit" {
		if words := ownersWords(event); words != nil {
			seat.LookSoon(&seat.Prompt{At: at, Said: *words})
			return
		}
	}
	seat.LookSoon(nil)
}

// questionStands is whether the seat keeps a question back or has one standing.
func questionStands(name string) bool { return seat.Kept(name) || notify.Standing(name) }
