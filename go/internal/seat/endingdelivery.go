package seat

import (
	"errors"
	"path/filepath"

	"agentkit/internal/job"
	"agentkit/internal/run"
)

var errTyped = errors.New("a line typed for it waits for its Enter")

// EndingDelivery is whether an ending is recorded and never typed (handback.routine_ending), or
// rides on the seat's next prompt (handback.ending_rides); neither, it is typed.  The hand-back, a
// look and a maintainer's merge use the same read of its plan and wait (Hears), the look and the
// tick's offer with the census its runs were read in.  A line already in the composer, or a read Go
// cannot make, leaves it pending, with an error: Go carries neither.
func EndingDelivery(record *run.Object, census []*run.Object, session string) (recordOnly, pending bool, err error) {
	if inOrder(record) {
		return true, false, nil // its job's one line says it
	}
	if !record.Truthy("merged") && record.Str("state") != "not_needed" {
		return false, false, nil
	}
	if record.Truthy("handback_typed") {
		return false, true, errTyped
	}
	if record.Truthy("repair") {
		return true, false, nil
	}
	now, rides, err := Hears(record, census, session)
	if err != nil {
		return false, true, err
	}
	return !now && !rides, rides, nil
}

// inOrder is Python's job.in_order: the run is a task of an ordered job.
func inOrder(record *run.Object) bool {
	if !record.Truthy("job_id") {
		return false
	}
	receipt, _ := job.Read(filepath.Join(job.Jobs(), record.Str("job_id")))
	return receipt != nil && receipt.Dict("opts") != nil && receipt.Dict("opts").Truthy("--in-order")
}
