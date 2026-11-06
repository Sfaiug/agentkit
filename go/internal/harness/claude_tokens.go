package harness

import (
	"path/filepath"
	"strings"

	"agentkit/internal/run"
)

// claudeTokenTypes are a message's counts in the order a usage row keeps them: input, cache
// write, cache read, output (claude.py TOKEN_TYPES).
var claudeTokenTypes = []string{"input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens", "output_tokens"}

// claudeTokenSources is the seat's conversation, written yet or not, and every subagent's beside
// it (claude.py `seat_token_sources`).
func claudeTokenSources(record *run.Object) []string {
	path := claudeConversation(map[string]any{"conversation": record.Str("conversation"), "cwd": record.Str("cwd"), "account": record.Str("account")})
	if path == "" {
		return nil
	}
	return append([]string{path}, below(filepath.Join(strings.TrimSuffix(path, ".jsonl"), "subagents"), "*.jsonl")...)
}

// claudeTokenUsage is an assistant message's usage, its four counts summed, keyed by the message:
// Claude Code writes a line for each block of a message, its usage on each (claude.py
// `seat_token_usage`).
func claudeTokenUsage(entry, _ *run.Object) (Spend, bool) {
	message := entry.Dict("message")
	if entry.Get("type") != "assistant" || message == nil || message.Dict("usage") == nil {
		return Spend{}, false
	}
	usage := message.Dict("usage")
	counts, said, tokens := make([]int, len(claudeTokenTypes)), false, 0
	for i, key := range claudeTokenTypes {
		if !usage.Has(key) {
			continue
		}
		count, whole := usage.Int(key)
		if !whole || count < 0 {
			return Spend{}, false
		}
		counts[i], said, tokens = count, true, tokens+count
	}
	event := message.Str("id")
	if event == "" {
		event = entry.Str("uuid")
	}
	var model any
	if named, ok := message.Get("model").(string); ok {
		model = named
	}
	return Spend{At: Moment(entry.Get("timestamp")), Event: event, Tokens: tokens, Model: model, Counts: counts}, said
}
