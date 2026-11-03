package harness

import (
	"strings"

	"agentkit/internal/config"
	"agentkit/internal/run"
)

// Looks is whether Go reads the screen of that harness's seats.
func Looks(name string) bool { return plugins[name].looks }

// RecordedError is the error a seat's conversation ends on, "" where it went on after one, as
// Python's plugin `error` reads it; false where its harness keeps no record of that conversation
// or it cannot be read, and only then is the screen the one to say.
func RecordedError(name string, record *run.Object) (string, bool) {
	if hook := plugins[name].recorded; hook != nil {
		return hook(record)
	}
	return "", false
}

// claudeError is the entry of its own a failed request ends in (claude.py `error`), its text and
// the kind it types apart from those words; a prompt or an answer after it is the conversation
// going on.
func claudeError(record *run.Object) (string, bool) {
	entry, err := lastEntry(claudeConversation(map[string]any{"conversation": record.Str("conversation"), "cwd": record.Str("cwd"), "account": record.Str("account")}), func(entry *run.Object) bool {
		return entry.Str("type") == "user" || entry.Str("type") == "assistant"
	})
	if err != nil {
		return "", false
	}
	if entry == nil || entry.Get("isApiErrorMessage") != true {
		return "", true
	}
	var parts []any
	if message := entry.Dict("message"); message != nil {
		if listed, ok := message.Get("content").([]any); ok {
			parts = listed
		} else if said, ok := message.Get("content").(string); ok {
			parts = []any{textPart(said)}
		}
	}
	if kind, ok := entry.Get("apiError").(string); ok {
		parts = append(parts, textPart(kind))
	}
	var said []string
	for _, part := range parts {
		if part, ok := part.(*run.Object); ok {
			if text, ok := part.Get("text").(string); ok {
				said = append(said, text)
			}
		}
	}
	return strings.TrimFunc(strings.Join(said, "\n"), config.Space), true
}

func textPart(text string) *run.Object {
	part := run.NewObject()
	part.Set("text", text)
	return part
}

// Says is whether text says word on its own, as Python's harness.says reads a word of one part.
func Says(text, word string) bool { return says(text, word) }

// Failure is the word a seat's error says in its `[stall]` words, and whether it is a spent or
// limited window, as a turn that ran reads it.  "" where it says none of them.
func Failure(name, said string) (string, bool) {
	ending, word := Ending(name, said, true)
	return word, ending == Spent
}
