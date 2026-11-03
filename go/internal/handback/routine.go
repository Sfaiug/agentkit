package handback

import (
	"agentkit/internal/config"
	"agentkit/internal/harness"
	"agentkit/internal/plan"
	"agentkit/internal/run"
	"agentkit/internal/seat"
)

// Delivered endings are recorded when no work is owed, or ride on the next prompt
// when they end no wait. An unread decision and a line awaiting its Enter stay pending.
func routineDelivery(record *run.Object, session string) (recordOnly, pending bool) {
	if !record.Truthy("merged") && record.Str("state") != "not_needed" {
		return false, false
	}
	if record.Truthy("handback_typed") {
		return false, true
	}
	if record.Truthy("repair") {
		return true, false
	}
	owes, err := plan.Owes(session)
	if err != nil {
		return false, true
	}
	if !owes {
		return true, false
	}
	own := config.SeatHarness(session)
	if own == "" {
		return false, true
	}
	if !harness.TakesContext(own) {
		return false, false
	}
	ends, err := seat.EndsWait(session, record)
	return false, err != nil || !ends
}
