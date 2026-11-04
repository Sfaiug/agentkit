package notify

import (
	"slices"

	"agentkit/internal/tmux"
)

// A dead pane keeps a tmux session, but its question's word still has the gone seat's reason.
func questionGone(name string) bool { return slices.Contains(tmux.Dead(tmux.Own()), name) }
