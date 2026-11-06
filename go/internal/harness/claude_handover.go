package harness

import (
	"strings"

	"agentkit/internal/run"
)

func claudeHanded(record *run.Object) (string, bool) {
	if record.Str("conversation") == "" || record.Str("cwd") == "" {
		return "It cannot be read here.\n\n", true
	}
	path := claudeConversation(map[string]any{"conversation": record.Str("conversation"), "cwd": record.Str("cwd"), "account": record.Str("account")})
	return handedMessages(path, record.Str("orchestrator"), claudeHandedMessage)
}

// claudeUnsaid marks the lines no one said here (claude.py UNSAID): bookkeeping, a compaction's
// summary, a subagent's, view-only ones.
var claudeUnsaid = []string{"isMeta", "isCompactSummary", "isSidechain", "isVisibleInTranscriptOnly"}

// The same visible words as claude.py prompt and answer; protocol frames, tools,
// compaction and subagents never become the conversation handed to another model.
func claudeHandedMessage(entry *run.Object) (string, string) {
	for _, key := range claudeUnsaid {
		if entry.Truthy(key) {
			return "", ""
		}
	}
	message := entry.Dict("message")
	switch entry.Str("type") {
	case "assistant":
		if message == nil || entry.Truthy("isApiErrorMessage") {
			return "", ""
		}
		content, _ := message.Get("content").([]any)
		return "model", handedText(content, "text")
	case "attachment":
		attachment := entry.Dict("attachment")
		if attachment != nil && attachment.Str("type") == "queued_command" && attachment.Dict("origin") != nil &&
			attachment.Dict("origin").Str("kind") == "human" && (!attachment.Has("commandMode") || attachment.Str("commandMode") == "prompt") {
			return "user", handedText(attachment.Get("prompt"), "text")
		}
	case "user":
		origin := entry.Dict("origin")
		if message == nil || message.Str("role") != "user" || origin != nil && origin.Get("kind") != nil && origin.Str("kind") != "human" {
			return "", ""
		}
		for _, value := range message.List("content") {
			if part, ok := value.(*run.Object); ok && part.Str("type") == "tool_result" {
				return "", ""
			}
		}
		text := handedText(message.Get("content"), "text")
		for _, frame := range []string{"<command-name>", "<local-command-stdout>", "<local-command-stderr>", "<local-command-caveat>", "<task-notification>"} {
			if strings.HasPrefix(text, frame) {
				return "", ""
			}
		}
		for frame, endings := range claudeNotices {
			for _, end := range endings {
				if text == frame+end {
					return "", ""
				}
			}
		}
		return "user", text
	}
	return "", ""
}
