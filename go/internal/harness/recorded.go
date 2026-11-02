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
func RecordedError(name, conversation, cwd string) (string, bool) {
	if hook := plugins[name].recorded; hook != nil {
		return hook(conversation, cwd)
	}
	return "", false
}

// claudeError is the entry of its own a failed request ends in (claude.py `error`), its text and
// the kind it types apart from those words; a prompt or an answer after it is the conversation
// going on.
func claudeError(conversation, cwd string) (string, bool) {
	entry, err := lastEntry(claudeConversation(map[string]any{"conversation": conversation, "cwd": cwd}), func(entry *run.Object) bool {
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

// The words every harness's failures use besides its manifest's (harness.STALL), but for the ones
// that say a turn never ran, which a seat's error line never is.
var (
	stallQuotas   = []string{"402", "billing_error", "payment required"}
	stallRefusals = []string{"API Error", "529", "unexpected status"}
	stallOutages  = []string{"overloaded", "at capacity", "Internal server error", "Bad Gateway", "Gateway Timeout",
		"Service unavailable", "The service is busy", "idle timeout", "Can't reach the API server", "HTTP~5##", "status~5##", "API Error~5##"}
)

// Failure is the word a seat's error says in its `[stall]` words, and whether it is a spent or
// limited window: a window outranks a refusal, and a refusal an outage, as Python's plugin
// `failure` reads a turn that ran.  "" where it says none of them.
func Failure(name, said string) (string, bool) {
	first := func(key string, own []string) string {
		words, _ := config.Words(name, "stall", key)
		for _, word := range append(words, own...) {
			if says(said, word) {
				return word
			}
		}
		return ""
	}
	if word := first("quotas", stallQuotas); word != "" {
		return word, true
	}
	if word := first("refusals", stallRefusals); word != "" {
		return word, false
	}
	return first("outages", stallOutages), false
}
