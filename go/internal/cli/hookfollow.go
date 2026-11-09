package cli

import (
	"os"

	"agentkit/internal/harness"
	"agentkit/internal/run"
	"agentkit/internal/seat"
)

// followed is the seat going on in the conversation its own Claude's /clear or /resume opened,
// as that SessionStart names it (claude.py `follow`), while the hook's caller still runs: only in
// a pane, the one place a hook can be the seat's own client's.  False where Go hands it over,
// with nothing written.
func followed(launched string, event *run.Object) bool {
	if !harness.ClaudeFollows(event) || os.Getenv("TMUX") == "" || os.Getenv("TMUX_PANE") == "" {
		return true
	}
	return seat.Claim(launched, "claude", event.Get("session_id"), event.Get("transcript_path"), os.Getppid(),
		harness.ClaudeClient, harness.ClaudeHook)
}
