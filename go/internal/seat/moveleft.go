package seat

import (
	"maps"

	"agentkit/internal/harness"
	"agentkit/internal/run"
)

// leaves adds the record's `left` to what the move writes, with the conversation it leaves added
// last (notify.left), as orch.switch_orchestrator keeps it for the seat's done check to read the
// owner's words in (notify.conversations_of): the one the seat's harness owns
// (orch.seat_conversation), where the move does not keep it (`kept`).  Each entry already there
// takes the record's account and directory where it has none; the one left is written beside
// them, and beside the file its harness keeps it in where that is there.  A launch that fails
// puts `left` back as the record had it (seatMove.launch).  False where Go does not know which
// conversation or file, or the record's `left` is none Python reads.
func (moving *seatMove) leaves(record map[string]any, selected *run.Object, kept string) bool {
	if kept != "" || moving.own == "" { // its model is gone: no harness names a conversation
		return true
	}
	owned, known := harness.Owned(moving.own, record)
	if !known || owned == "" {
		return known
	}
	there := maps.Clone(record)
	there["conversation"] = owned
	file, known := harness.Conversation(moving.own, there)
	had, listed := selected.Get("left").([]any)
	if !known || selected.Has("left") && !listed {
		return false
	}
	then := func(entry *run.Object) *run.Object {
		entry.Set("account", selected.Get("account"))
		entry.Set("cwd", selected.Get("cwd"))
		return entry
	}
	var gone []any
	for _, each := range had {
		was, _ := each.(*run.Object)
		if was == nil {
			return false
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
	moving.chosen = append(moving.chosen, field{"left", append(gone, now)})
	return true
}
