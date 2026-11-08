package notify

import (
	"agentkit/internal/config"
	"agentkit/internal/harness"
	"agentkit/internal/history"
	"agentkit/internal/run"
)

// owed is the owner's time a notice starts, which Python's _said writes once it has recorded the
// notice: a row `asked` for each question it asks for the first time (said's `fresh`), dated as the
// notice dates that question, in the seat's conversation.  False where a row is owed and Go cannot
// name that conversation as Python does.
func owed(name string, notice *run.Object, fresh []string) (func(), bool) {
	if len(fresh) == 0 {
		return func() {}, true
	}
	conversation, named := ConversationOf(name)
	if !named {
		return nil, false
	}
	return func() {
		for _, question := range fresh {
			at, _ := notice.Dict("asked_at").Num(questionKey(question))
			history.OwnerTime("asked", at, nil, conversation)
		}
	}, true
}

// ConversationOf is notify.conversation_of as an owner row names it, `<harness>:<id>`, nil where
// the seat has no record or its harness says it holds none; false where Go cannot say which it
// holds.
func ConversationOf(name string) (any, bool) {
	current, record, err := config.ResolveSession(name)
	if err != nil || len(record) == 0 {
		return nil, err == nil
	}
	own := config.SeatHarness(current)
	conversation, known := harness.Owned(own, record)
	if own == "" || !known || conversation == "" {
		return nil, own != "" && known
	}
	return own + ":" + conversation, true
}
