package seat

import (
	"path/filepath"

	"agentkit/internal/config"
	"agentkit/internal/harness"
	"agentkit/internal/job"
	"agentkit/internal/plan"
	"agentkit/internal/run"
)

// EndingDelivery is whether an ending is recorded and never typed (handback.routine_ending), or
// rides on the seat's next prompt (handback.ending_rides); neither, it is typed.  The hand-back, a
// look and a maintainer's merge use the same read of its plan and wait, the look and the tick's
// offer with the census its runs were read in.  A line already in the composer, or a read Go
// cannot make, leaves it pending.
func EndingDelivery(record *run.Object, census []*run.Object, session string) (recordOnly, pending bool) {
	if inOrder(record) {
		return true, false // its job's one line says it
	}
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
	ends, err := EndsWait(session, census, record)
	switch {
	case err != nil:
		return false, true
	case ends:
		return false, false
	case harness.TakesContext(own):
		return false, true
	}
	return true, false // nothing in it is the seat's to decide, and no prompt carries it
}

// inOrder is Python's job.in_order: the run is a task of an ordered job.
func inOrder(record *run.Object) bool {
	if !record.Truthy("job_id") {
		return false
	}
	receipt, _ := job.Read(filepath.Join(job.Jobs(), record.Str("job_id")))
	return receipt != nil && receipt.Dict("opts") != nil && receipt.Dict("opts").Truthy("--in-order")
}
