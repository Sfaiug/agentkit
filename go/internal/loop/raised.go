package loop

import "agentkit/internal/run"

// Raised is whether Go carries on the FAIL at its round budget that read was, now that an order
// (`ak run resume --rounds`) raised its budget in record: from its next round's start, as Pickup
// takes up a dead run there.
func Raised(dir string, read, record *run.Object) bool {
	return run.AtBudget(read) && !run.AtBudget(record) && carriedOn(dir, record)
}
