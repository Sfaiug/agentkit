package harness

import (
	"sort"

	"agentkit/internal/config"
	"agentkit/internal/hookfact"
)

// A Turn is one message of a conversation as its harness shows it: the user side's or the model's.
type Turn struct{ Who, Text string }

// Said is that conversation as its harness shows it, oldest first, read from the harness's own
// store each time: what the user side typed, ak included, and the model's visible answers, never
// tool calls or results, thinking or subagents; none where it keeps no record of it.  False where
// Go does not read that harness's words (Python's plugin `said`).
func Said(name, conversation string) ([]Turn, bool) {
	if hook := plugins[name].said; hook != nil {
		return hook(conversation), true
	}
	return nil, false
}

// A Prompt is one of the owner's messages: when it was written, in Unix seconds, and its words.
type Prompt struct {
	At   float64
	Text string
}

// Typed is what the user side typed in the conversation that seat's record owns, oldest first, and
// that conversation, as Python's plugin `conversation` and `user_messages` read them: nothing for
// a seat owning none (notify.owner_messages); false where that harness has no reader of its own,
// or Owned does not know the conversation.
func Typed(name string, record map[string]any) (conversation string, typed []Prompt, known bool) {
	own := plugins[name]
	if own.owned == nil && own.typed == nil {
		return "", nil, false
	}
	if conversation, known = Owned(name, record); !known || conversation == "" || own.typed == nil {
		return "", nil, known && conversation == ""
	}
	typed = own.typed(conversation)
	sort.SliceStable(typed, func(i, j int) bool { return typed[i].At < typed[j].At })
	return conversation, typed, true
}

// seatFact is watch.seat_fact: the seat's hook fact, or the question card its harness recorded
// since, as the fact that card's going up or settling writes.  A card no hook of the seat's launch
// hears, in a conversation the harness opened after it, still blocks it, and its settling still
// ends that.
func (own plugin) seatFact(name string) hookfact.Fact {
	fact := hookfact.Standing(name)
	if own.card == nil {
		return fact
	}
	current, record, err := config.ResolveSession(name)
	if err != nil || record == nil || current != config.Fold(name) {
		return fact
	}
	card, up := own.card(own.owned(record))
	if !up || fact.At != 0 && card.At <= fact.At {
		return fact
	}
	card.Session = name
	return card
}
