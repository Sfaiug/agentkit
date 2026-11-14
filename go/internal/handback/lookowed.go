package handback

import "agentkit/internal/run"

// LookOwed is Python's _look_owed: whether the seat's own look prints the run's line, none waiting
// in its composer: its ending waits for the seat, its ending or its going live was recorded, or
// its going live is owed with nothing typed for it.  An error where Go cannot read that as Python
// does.
func LookOwed(record *run.Object) (bool, error) {
	switch {
	case record.Truthy("handback_typed"):
		return false, nil
	case run.Waits(record) || record.Str("handback_note") == routine || record.Str("live_note") == routine:
		return true, nil
	case record.Truthy("live_typed") || !record.Truthy("live_at"):
		return false, nil
	}
	owed, _, err := liveOwed(record, nil)
	return owed, err
}

// lookOwes is LookOwed where Go reads it: a read it cannot make leaves the ending to the tick.
func lookOwes(record *run.Object) bool {
	owed, err := LookOwed(record)
	return owed && err == nil
}
