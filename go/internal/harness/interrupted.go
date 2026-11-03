package harness

import (
	"slices"

	"agentkit/internal/run"
)

// LastMessage is the last message of a seat's conversation (the claude.py hooks that read back from
// its end), nil for none, or where that harness records none Go reads.
func LastMessage(name, conversation, cwd, account string) *run.Object {
	if hook := plugins[name].last; hook != nil {
		return hook(conversation, cwd, account)
	}
	return nil
}

// Interrupts is whether that message is its harness's record of the owner interrupting the turn, an
// end it reports by no hook (claude.py `interrupted`).
func Interrupts(name string, entry *run.Object) bool {
	message := entry.Dict("message")
	if entry.Str("type") != "user" || message == nil {
		return false
	}
	parts := message.List("content")
	if parts == nil {
		text := run.NewObject()
		text.Set("text", message.Get("content"))
		parts = []any{text}
	}
	return slices.ContainsFunc(parts, func(part any) bool {
		said, _ := part.(*run.Object)
		if said == nil {
			return false
		}
		text, _ := said.Get("text").(string)
		for opening, ends := range plugins[name].notices {
			if slices.ContainsFunc(ends, func(end string) bool { return text == opening+end }) {
				return true
			}
		}
		return false
	})
}

// claudeLast is the last entry a turn's speaker wrote: its other entries are bookkeeping.
func claudeLast(conversation, cwd, account string) *run.Object {
	entry, _ := lastEntry(claudeConversation(map[string]any{"conversation": conversation, "cwd": cwd, "account": account}), func(entry *run.Object) bool {
		return entry.Str("type") == "user" || entry.Str("type") == "assistant"
	})
	return entry
}
