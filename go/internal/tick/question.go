package tick

import (
	"agentkit/internal/lifecycle"
	"agentkit/internal/notify"
	"agentkit/internal/seat"
)

// questionRead is a question of the seat's own standing whose answer in its conversation Go reads:
// unanswered, or answered there where its stop is typed at it, whose stop nudge answers it first as
// Python's does.  Kept questions and screen dialogs are left to their Python passes.
func questionRead(live seat.Live) bool {
	nudged, err := lifecycle.Nudged(live.Own)
	return !live.File.Truthy("unasked") && live.State != "asking" &&
		(notify.UnansweredQuestion(live.Name) || err == nil && nudged && notify.QuestionRead(live.Name))
}
