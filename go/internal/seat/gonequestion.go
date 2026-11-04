package seat

import "agentkit/internal/notify"

// A question keeps an unowned saved seat visible. An owned conversation is judged separately
// at the tick's revival row.
func (seat Seat) waitingQuestion() bool { return seat.unowned && notify.UnansweredQuestion(seat.Name) }

func goneQuestionKind(kind, name, suffix string) bool {
	return kind == "notify" && suffix == "json" && notify.UnansweredQuestion(name)
}
