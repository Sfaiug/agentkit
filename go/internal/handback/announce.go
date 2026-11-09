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

// Reaches is whether Give reaches the seat that launched the run, the owner in its stead, or the
// job whose one line says it: up on ak's own server, nothing left of it (Orphaned), gone from under
// a job's task (muted), or asleep where Go wakes it, for an ending typed into it
// (handback.announce): one that merged or was not needed may be recorded or ride on its next
// prompt, which wakes nothing.  Never where Go cannot read how its change going live meets it.
func Reaches(record *run.Object) bool {
	session := run.Seat(record)
	_, _, unread := liveEnding(record)
	return (seat.Watching(session) || Orphaned(record) || muted(record) ||
		run.Ended(record) && !record.Truthy("merged") && record.Str("state") != "not_needed" && seat.Wakes(session)) &&
		unread == nil
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
