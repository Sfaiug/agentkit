package seat

import (
	"strconv"

	"agentkit/internal/harness"
	"agentkit/internal/tmux"
)

// Backoff cannot claim a death whose recovery belongs to another path.
func (seat Seat) supportsRunRevival(record map[string]any) bool {
	if _, opens := harness.Opens(seat.own); !opens {
		return false
	}
	// An old record with no launch has no pane-died recovery claim.
	if launched, dated := record["launched"].(float64); dated && seat.held {
		said, err := tmux.Ask(tmux.Own(), "display-message", "-p", "-t", harnessPane(seat.Name), "#{pane_dead_time}")
		died, unread := strconv.ParseFloat(said, 64)
		return err == nil && unread == nil && died-launched < Warmup.Seconds()
	}
	return true
}
