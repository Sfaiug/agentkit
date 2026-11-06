package seat

import (
	"cmp"
	"time"

	"agentkit/internal/tmux"
)

// Explanation uses the observation that decided the row and its bar, without another look.
func (seat Seat) Explanation(now time.Time) []string {
	lines := []string{seat.Name + "  " + seat.Word, "  reason:    " + cmp.Or(seat.reason, "-")}
	if !seat.live {
		return append(lines, "  authority: -     the process is gone; nothing here read its screen")
	}
	return append(lines,
		"  authority: "+cmp.Or(seat.seen.authority, "default")+"  rule: "+cmp.Or(seat.seen.rule, "-"),
		"  evidence:  "+cmp.Or(seat.seen.evidence, "nothing on the screen said otherwise"),
		"  since:     "+sinceLine(seat.since, now))
}

// Path is the session's current directory, or the launch directory when tmux has lost it.
func (seat Seat) Path() string {
	if seat.live || seat.held {
		if path, err := tmux.Ask(seat.server(), "display-message", "-p", "-t", "="+seat.Name+":", "#{pane_current_path}"); err == nil {
			return path
		}
	}
	return seat.path
}
