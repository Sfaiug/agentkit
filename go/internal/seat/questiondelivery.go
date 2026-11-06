package seat

import (
	"agentkit/internal/config"
	"agentkit/internal/harness"
	"agentkit/internal/lifecycle"
	"agentkit/internal/run"
)

// repeatingQuestion: a question its closing message left out is not the owner's yet, while its
// composer is open and no usage wait holds the seat: it goes back (questions.unseen).
func repeatingQuestion(facts climbing) (*answer, error) {
	if facts.gone != nil || facts.own == "" || !facts.found.composerOpen(facts.own) {
		return nil, nil
	}
	reminder, err := questionUnseen(facts.name, facts.own, facts.found, facts.notice)
	if err != nil || reminder == "" {
		return nil, err
	}
	if waiting, err := usage(facts); waiting != nil || err != nil {
		return nil, err
	}
	return &answer{word: "working", reason: "repeating its question in the chat", since: facts.found.began}, nil
}

// questionUnseen is questions.unseen: the reminder a seat with no blocking Stop is owed while a question it
// recorded is not in its closing message, the newest in its conversation and only if the model's.
// After a turn the owner interrupted, or for a seat owning no conversation, nothing: it rests, as
// nothing would ever prove it seen.  ErrUnread where Go does not read that harness's words.  notice
// is the seat's standing one.
func questionUnseen(name, own string, found sight, notice *run.Object) (string, error) {
	nudged, err := lifecycle.Nudged(own)
	if err != nil {
		return "", ErrUnread
	}
	asked := pending(name, notice)
	if !nudged || found.interrupted || len(asked) == 0 {
		return "", nil
	}
	_, record, err := config.ResolveSession(name)
	if err != nil {
		return "", ErrUnread
	}
	conversation, known := harness.Owned(own, record)
	if !known {
		return "", ErrUnread
	}
	if record == nil || conversation == "" {
		return "", nil
	}
	said, known := harness.Said(own, conversation)
	if !known {
		return "", ErrUnread
	}
	closing := ""
	if len(said) > 0 && said[len(said)-1].Who == "model" {
		closing = said[len(said)-1].Text
	}
	return reminder(closing, asked), nil
}
