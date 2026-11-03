package harness

import (
	"agentkit/internal/config/adapters"
	"agentkit/internal/run"
)

// WrappedUp is when the conversation a seat's record names had its latest turn wrapped up for a
// spent subscription, no prompt since, as that harness notes it (its plugin's `wrapped_up`): the
// turn stopped with nothing refused.  Nil where it was not, or its harness notes no such turn;
// prompted is whether an entry holds the owner's prompt.
func WrappedUp(name string, record map[string]any, prompted func(*run.Object) bool) any {
	if hook := plugins[name].wrapped; hook != nil {
		return hook(record, prompted)
	}
	return nil
}

// claudeWrapped is claude.py's `wrapped_up`: Claude Code's own note of a turn wrapped up
// (adapters.ClaudeWrapUp), its time, where it is the last such note or prompt.
func claudeWrapped(record map[string]any, prompted func(*run.Object) bool) any {
	note := func(entry *run.Object) bool {
		return entry.Get(adapters.ClaudeWrapUp.Key) == adapters.ClaudeWrapUp.Value
	}
	entry, _ := lastEntry(claudeConversation(record), func(entry *run.Object) bool { return note(entry) || prompted(entry) })
	if entry == nil || !note(entry) {
		return nil
	}
	return entry.Get("timestamp")
}
