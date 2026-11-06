package seat

import (
	"agentkit/internal/config"
	"agentkit/internal/harness"
	"agentkit/internal/plan"
	"agentkit/internal/run"
)

// EndingDelivery is whether an ending is recorded without typing, or rides on the seat's
// next prompt. The hand-back and a look use the same read of its plan and wait, the look with the
// census its runs were read in.
func EndingDelivery(record *run.Object, census []*run.Object, session string) (recordOnly, pending bool) {
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
	ends, err := EndsWait(session, census, record)
	return false, err != nil || !ends
}
