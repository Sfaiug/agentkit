package harness

import (
	"path"
	"strings"

	"agentkit/internal/agent"
	"agentkit/internal/run"
)

// claudeHook is the id_source of a conversation a Claude seat's own hook reported (claude.py
// SOURCE).
const claudeHook = "claude-hook"

// Followed is a conversation a hook's event says a seat's own client went on in (Harness.follow):
// the harness whose seat it moves, the conversation and its transcript as the event names them,
// whether a process runs that harness's own client, and the id_source the record takes with it.
// Filed is where that harness files a conversation for the seat whose record that is, nil for its
// plugin's `conversation` (harness.claim's `filed`); Keep keeps the conversation among those the
// seat left and moves nothing (harness.claim's `keep`).
type Followed struct {
	Harness, Source          string
	Conversation, Transcript any
	Client                   func(words []string) bool
	Filed                    func(record map[string]any, conversation string) string
	Keep                     bool
}

// claudeFollows is only Claude's /clear, which opens a new conversation, and /resume, which goes
// back to an earlier one, as their SessionStart names it, and never a sub-agent's (claude.py
// `follow`).
func claudeFollows(event *run.Object) *Followed {
	source := event.Get("source")
	if event.Get("hook_event_name") != "SessionStart" || source != "clear" && source != "resume" ||
		event.Truthy("agent_id") || event.Truthy("agent_type") {
		return nil
	}
	return &Followed{Harness: "claude", Source: claudeHook, Conversation: event.Get("session_id"),
		Transcript: event.Get("transcript_path"), Client: claudeClient}
}

// claudeClient is whether a process runs Claude Code's own client (claude.py `is_process`): its
// native program, or npm's Node entry point.
func claudeClient(words []string) bool {
	program := agent.Program(words, true)
	return path.Base(program) == "claude" || strings.HasSuffix(program, "/@anthropic-ai/claude-code/cli.js")
}
