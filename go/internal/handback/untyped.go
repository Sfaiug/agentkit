package handback

import (
	"path/filepath"

	"agentkit/internal/job"
	"agentkit/internal/plan"
	"agentkit/internal/run"
)

// Untyped is whether a delivered run's ending is never typed into its seat, Python's
// routine_ending or ending_rides: a task of an ordered job, whose one line says it, a repair, a
// seat owing no work, or an ending that ends no wait of the seat's (ends_wait).  Whether it is
// then recorded or rides the seat's next prompt is the hand-back's; a line already in the
// composer is the caller's.
func Untyped(record *run.Object) (bool, error) {
	session := run.Seat(record)
	if inOrder(record) || record.Truthy("repair") || session == "" {
		return true, nil
	}
	if owes, err := plan.Owes(session); !owes || err != nil {
		return !owes, err
	}
	ends, err := endsWait(record)
	return !ends, err
}

// inOrder is Python's job.in_order: the run is a task of an ordered job.
func inOrder(record *run.Object) bool {
	if !record.Truthy("job_id") {
		return false
	}
	receipt, _ := job.Read(filepath.Join(job.Jobs(), record.Str("job_id")))
	return receipt != nil && receipt.Dict("opts") != nil && receipt.Dict("opts").Truthy("--in-order")
}
