package harness

import (
	"path"
	"strings"

	"agentkit/internal/agent"
	"agentkit/internal/run"
)

// ClaudeHook is the id_source of a conversation a Claude seat's own hook reported (claude.py
// SOURCE).
const ClaudeHook = "claude-hook"

// ClaudeFollows is whether a hook's event reports the conversation a Claude seat goes on in
// (claude.py `follow`): the SessionStart of a /clear, which opens a new one, or of a /resume,
// which goes back to an earlier one, and never a sub-agent's.
func ClaudeFollows(event *run.Object) bool {
	source := event.Get("source")
	return event.Get("hook_event_name") == "SessionStart" && (source == "clear" || source == "resume") &&
		!event.Truthy("agent_id") && !event.Truthy("agent_type")
}

// ClaudeClient is whether a process runs Claude Code's own client (claude.py `is_process`): its
// native program, or npm's Node entry point.
func ClaudeClient(words []string) bool {
	program := agent.Program(words, true)
	return path.Base(program) == "claude" || strings.HasSuffix(program, "/@anthropic-ai/claude-code/cli.js")
}
