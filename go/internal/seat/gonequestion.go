package seat

import "agentkit/internal/notify"

// A question keeps a saved seat visible even when its conversation is no longer resumable.
func (seat Seat) waitingQuestion() bool { return notify.UnansweredQuestion(seat.Name) }

func goneQuestionKind(kind, name, suffix string) bool {
	return kind == "notify" && suffix == "json" && notify.UnansweredQuestion(name)
}
