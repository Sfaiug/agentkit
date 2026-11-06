package tick

import "agentkit/internal/seat"

// typedAnswers is notify.answer_typed: a message the owner typed while a seat's turn ran went into
// that turn, and no prompt hook heard it, so it answers by the conversation.
func (t *ticking) typedAnswers() error {
	names, known := seat.Seats(t.clock())
	if !known {
		return errLeft
	}
	for _, name := range names {
		done, err := seat.AnswerWritten(name)
		if err != nil {
			return err
		}
		if done {
			t.log.line(name + ": its question was answered in the turn it was asked in")
		}
	}
	return nil
}
