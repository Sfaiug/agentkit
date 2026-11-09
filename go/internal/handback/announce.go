package handback

import (
	"time"

	"agentkit/internal/run"
	"agentkit/internal/seat"
)

func recoveryEnding(record *run.Object) bool { return record.Str("state") == "interrupted" }

// Awaiting includes an interruption's recovery notice, which uses the same decision line
// and delivery lock as a finished run (handback.notify_recovery): a run no seat launched has
// nobody to give it to.
func Awaiting(record *run.Object, now time.Time) bool {
	return Owed(record, now) || recoveryEnding(record) && run.Launched(record) != "" && !record.Truthy("handed_back") &&
		!record.Truthy("reported") && !record.Truthy("recovery_notified") && !record.Truthy("recovery_acknowledged_at")
}

// Reaches is whether Give reaches the seat that launched the run, or the owner in its stead: up
// on ak's own server, nothing left of it (Orphaned), or neither, for an ending that wakes nothing,
// recorded, riding on its next prompt or held for its change to go live, as Python's announce
// decides before it wakes anything; else asleep where Go wakes it, for an ending typed into it.
// Never where Go cannot read how the seat hears it, or how its change going live meets it.  From
// census as Give reads it.
func Reaches(record *run.Object, census []*run.Object) bool {
	reaches, _ := reach(record, census)
	return reaches
}

// reach is Reaches, and whether Give wakes the seat first.
func reach(record *run.Object, census []*run.Object) (reaches, wakes bool) {
	session := run.Seat(record)
	held, _, err := liveEnding(record, census)
	switch {
	case err != nil:
		return false, false
	case seat.Watching(session) || Orphaned(record):
		return true, false
	case !run.Ended(record):
		return false, false // an interruption's notice to a seat not up is Python's (notify_recovery)
	}
	recordOnly, pending, err := seat.EndingDelivery(record, census, session)
	switch {
	case err != nil:
		return false, false
	case recordOnly || pending || held:
		return true, false
	}
	wakes = seat.Wakes(session)
	return wakes, wakes
}

// Announce offers an ending through the run's own hand-back, from census as Give reads it, keeping
// its pending mark when its seat cannot take the line yet.
func Announce(dir string, census []*run.Object, say func(string)) bool {
	record, _ := run.Read(dir)
	if record == nil || !Awaiting(record, time.Now()) || !Give(dir, census, say) {
		return false
	}
	if recoveryEnding(record) {
		mark(dir, record, "recovery_notified", "orchestrator")
	}
	return true
}
