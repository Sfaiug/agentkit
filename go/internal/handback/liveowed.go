package handback

import (
	"agentkit/internal/run"
	"agentkit/internal/seat"
)

// liveOwed is Python's live_owed, live_at aside: whether the seat of the merged run still has to
// hear that its change went live (seat.Hears), and whether it hears it on its next prompt (rides)
// rather than now, from census as EndsWait reads it; an error where Go cannot read it as Python
// does.
func liveOwed(record *run.Object, census []*run.Object) (owed, rides bool, err error) {
	if !record.Truthy("merged") || record.Truthy("live_notified") {
		return false, false, nil
	}
	now, rides, err := seat.Hears(record, census, run.Seat(record))
	return now || rides, rides, err
}

// livePass is how telling that the merged run went live goes, as Python's live_passed decides it
// under the run's delivery lock: recorded and never typed where its seat need not hear it
// (live_owed); nothing done where its ending's own line says it (carries_live) or it rides on the
// seat's next prompt (rides); typed alone into the seat otherwise, which is Python's (left), as are
// a line an earlier pass typed for it, which gets its Enter first, and a read Go cannot make.
func livePass(record *run.Object) (recorded, left bool) {
	owed, rides, err := liveOwed(record, nil)
	typed := record.Dict("live_typed")
	switch {
	case err != nil:
		return false, true
	case !owed:
		return true, typed != nil && typed.Truthy("line")
	}
	return false, !saysLive(record) && (!rides || record.Truthy("live_typed"))
}
