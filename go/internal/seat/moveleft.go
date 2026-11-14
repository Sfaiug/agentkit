package seat

import (
	"encoding/json"
	"maps"
	"slices"

	"agentkit/internal/harness"
	"agentkit/internal/run"
)

// conversationChanged refuses a move made from a conversation the seat is no longer on.
const conversationChanged = Refusal("the seat's conversation changed before it could move")

// leaves is whether Go makes the `left` of a move onto a new conversation (`kept` ""), settled on
// the record as planned, before anything is written; the move makes it again from the record its
// write finds (fields).  Its model gone, no harness names a conversation it leaves.
func (moving *seatMove) leaves(record map[string]any, selected *run.Object, kept string) bool {
	moving.leaving = kept == "" && moving.own != ""
	_, known := moving.left(record, selected)
	return known
}

// fields is what the move writes over data, the seat's record under its lock: the fields it takes,
// with the `left` made from data, so a /clear claimed while the owner was asked keeps the
// conversations it kept.  False where Go cannot make it there.
func (moving *seatMove) fields(data *run.Object) ([]field, bool) {
	var record map[string]any // as config.ResolveSession reads a record
	json.Unmarshal([]byte(run.Line(data)), &record)
	gone, known := moving.left(record, data)
	if gone == nil {
		return moving.chosen, known
	}
	return append(slices.Clip(moving.chosen), field{"left", gone}), true
}

// left is the record's `left` with the conversation the move leaves added last (notify.left), as
// orch.switch_orchestrator keeps it for the seat's done check to read the owner's words in
// (notify.conversations_of): the one the seat's harness owns (orch.seat_conversation).  Each entry
// already there takes the record's account and directory where it has none; the one left is
// written beside them, and beside the file its harness keeps it in where that is there.  Nil where
// the move leaves none; false where Go does not know which conversation or file, or the record's
// `left` is none Python reads.
func (moving *seatMove) left(fields map[string]any, record *run.Object) (any, bool) {
	if !moving.leaving {
		return nil, true
	}
	owned, known := harness.Owned(moving.own, fields)
	if !known || owned == "" {
		return nil, known
	}
	there := maps.Clone(fields)
	there["conversation"] = owned
	file, known := harness.Conversation(moving.own, there)
	had, listed := record.Get("left").([]any)
	if !known || record.Has("left") && !listed {
		return nil, false
	}
	then := func(entry *run.Object) *run.Object {
		entry.Set("account", record.Get("account"))
		entry.Set("cwd", record.Get("cwd"))
		return entry
	}
	var gone []any
	for _, each := range had {
		was, _ := each.(*run.Object)
		if was == nil {
			return nil, false
		}
		entry := then(run.NewObject())
		for _, key := range was.Keys() {
			entry.Set(key, was.Get(key))
		}
		gone = append(gone, entry)
	}
	now := run.NewObject()
	now.Set("harness", moving.own)
	now.Set("conversation", owned)
	if then(now); file != "" && exists(file) {
		now.Set("transcript", file)
	}
	return append(gone, now), true
}
