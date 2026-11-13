package harness

import "agentkit/internal/run"

// opencodeMoves is whether a prompt names the session the seat's own OpenCode took it into, which
// moves the seat there where that session is top-level (opencode.py `follow`).
func opencodeMoves(event *run.Object) bool {
	session, _ := event.Get("session_id").(string)
	return event.Get("hook_event_name") == "UserPromptSubmit" && opencodeSession.MatchString(session)
}
