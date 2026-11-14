package seat

import (
	"strings"

	"agentkit/internal/tmux"
)

// starts is when tmux last started each session that server holds (orch.server_sessions).
func starts(server string) map[string]int {
	said, _ := tmux.Ask(server, "list-sessions", "-F", "#{session_name}\t#{session_created}")
	born := map[string]int{}
	for _, line := range strings.Split(said, "\n") {
		if session, at, ok := strings.Cut(line, "\t"); ok {
			born[session] = created(at)
		}
	}
	return born
}

// Started is when the seat's row is aged from (orch.list_table): tmux's last start of the session
// it holds, asked once a reading and only where an age is drawn, else its record's first launch,
// which orders it either way (orch.numbered).
func (seat Seat) Started() float64 {
	if seat.starts != nil {
		if at, held := seat.starts()[seat.Name]; held {
			return float64(at)
		}
	}
	return seat.Created
}
