package seat

import (
	"agentkit/internal/lifecycle"
	"agentkit/internal/notify"
)

// repeatingQuestion: only a pending question needs its delivery proved from the conversation
// (questions.unseen). Go leaves that proof for a harness with no blocking Stop to Python.
func repeatingQuestion(facts climbing) (*answer, error) {
	if facts.gone != nil || !notify.OwnerQuestion(facts.notice) && len(questionsKept(facts.file.Dict("unasked"), nil)) == 0 {
		return nil, nil
	}
	if nudged, err := lifecycle.Nudged(facts.own); err != nil || nudged {
		return nil, ErrUnread
	}
	return nil, nil
}
