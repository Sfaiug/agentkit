package tick

import (
	"agentkit/internal/notify"
	"agentkit/internal/seat"
)

// unansweredQuestion leaves typed answers, kept questions and screen dialogs to their Python passes.
func unansweredQuestion(live seat.Live) bool {
	return !live.File.Truthy("unasked") && live.State != "asking" && notify.UnansweredQuestion(live.Name)
}
