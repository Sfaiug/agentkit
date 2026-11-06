package notify

import (
	"strconv"
	"strings"

	"agentkit/internal/tmux"
)

// A missing tmux session has no owner present or last input; Python's notify._last_input also
// reads a failed display-message as zero.  tmux 3.5 answers one with every field empty, and no
// error.
func questionActivity(name string) (present bool, last float64, gone, known bool) {
	activity, err := tmux.Ask(tmux.Own(), "display-message", "-p", "-t", "="+name+":",
		"#{session_attached}\t#{session_activity}")
	if err != nil || activity == "" {
		return false, 0, true, true
	}
	parts := strings.Fields(activity)
	if len(parts) != 2 {
		return false, 0, false, false
	}
	at, err := strconv.ParseInt(parts[1], 10, 64)
	gone = questionGone(name)
	return !gone && parts[0] != "0", float64(at), gone, err == nil
}
