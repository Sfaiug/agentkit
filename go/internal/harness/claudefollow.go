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
type Followed struct {
	Harness, Source          string
	Conversation, Transcript any
	Client                   func(words []string) bool
}

// Follows is the conversation a hook's event reports a seat going on in, nil where it reports
// none: only Claude's /clear, which opens a new one, and /resume, which goes back to an earlier
// one, as their SessionStart names it, and never a sub-agent's (claude.py `follow`).
func Follows(event *run.Object) *Followed {
	source := event.Get("source")
	if event.Get("hook_event_name") != "SessionStart" || source != "clear" && source != "resume" ||
		event.Truthy("agent_id") || event.Truthy("agent_type") {
		return nil
	}
	return &Followed{"claude", claudeHook, event.Get("session_id"), event.Get("transcript_path"), claudeClient}
}

// claudeClient is whether a process runs Claude Code's own client (claude.py `is_process`): its
// native program, or npm's Node entry point.
func claudeClient(words []string) bool {
	program := agent.Program(words, true)
	return path.Base(program) == "claude" || strings.HasSuffix(program, "/@anthropic-ai/claude-code/cli.js")
}
