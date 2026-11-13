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

// How telling that a merged run went live goes (livePass).
const (
	liveUntold   = iota // nothing done now: its ending's own line says it, or it rides on the seat's next prompt
	liveRecorded        // recorded and never typed
	liveTyped           // typed alone into its seat (tellLive)
	liveLeft            // Python's
)

// livePass is how telling that the merged run went live goes, as Python's live_passed decides it
// under the run's delivery lock: recorded and never typed where its seat need not hear it
// (live_owed); nothing done where its ending's own line says it (carries_live) or it rides on the
// seat's next prompt (rides); typed alone into the seat otherwise.  A line an earlier pass typed for
// it, which gets its Enter first, is Python's, as is a read Go cannot make.  The seat's other runs
// are read from census, the merge checks' one read of every run.
func livePass(record *run.Object, census []*run.Object) int {
	owed, rides, err := liveOwed(record, census)
	typed := record.Dict("live_typed")
	switch {
	case err != nil, !owed && typed != nil && typed.Truthy("line"):
		return liveLeft
	case !owed:
		return liveRecorded
	case saysLive(record):
		return liveUntold
	case record.Truthy("live_typed"):
		return liveLeft
	case rides:
		return liveUntold
	}
	return liveTyped
}
