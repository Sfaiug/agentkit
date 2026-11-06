package cli

import (
	"agentkit/internal/run"
	"agentkit/internal/seat"
)

// heardAnswer is what the seat's hook heard that may answer its question: a prompt in the owner's
// words, which its look after the event checks (hooks/seat-state.sh's `look`), or their answer on
// the harness's own question card, which is recorded here (seat.AnswerCard); nil for anything
// else.  False where that answer is Python's to record, with nothing written.
func heardAnswer(event *run.Object, at float64, row string) (*seat.Prompt, bool) {
	switch event.Str("hook_event_name") {
	case "UserPromptSubmit":
		if words := ownersWords(event); words != nil {
			return &seat.Prompt{At: at, Said: *words}, true
		}
	case "PostToolUse":
		if replies := cardReplies(event); replies != nil {
			return nil, seat.AnswerCard(row, at, replies)
		}
	}
	return nil, true
}

// lookAfter has the seat looked at again once its hook's event is down, with what it heard.
func lookAfter(heard *seat.Prompt) { seat.LookSoon(heard) }
