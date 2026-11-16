package run

import "strings"

// ResumeOrdered is whether a resume the tick ordered is still the one to adopt the record: its
// `stall_resume_at` inside handback.STALL_RESUME_GRACE, while reap leaves the dead loop alone.
func ResumeOrdered(record *Object, now float64) bool {
	at, ok := record.Num("stall_resume_at")
	return ok && 0 <= now-at && now-at < 600
}

// GoesOn is whether reap leaves a live record's loop to go on: its process alive, a waiter holding
// its place for the tick to adopt, its launch inside its grace, its resume ordered, or the backoff
// after its death being waited out.
func GoesOn(record *Object, now float64) bool {
	until, holding := record.Num("resume_after")
	return ProcessActive(record) || record.Str("state") == "queued" && record.Truthy("slot_waiting") ||
		LaunchGrace(record, now) || ResumeOrdered(record, now) || holding && now < until
}

// LaunchGrace is whether a queued launch is still inside handback.QUEUED_GRACE, before its
// launcher's own process is recorded.
func LaunchGrace(record *Object, now float64) bool {
	if record.Str("state") != "queued" || !record.Truthy("launch_pending") && record.Truthy("process_identity") {
		return false
	}
	at := FirstNumber(record, "queued_at", "started_at")
	return now-at < 30
}

// Scoped is whether a unit the manager holds ran that loop (turns.scope_is_real).
func Scoped(record *Object) bool {
	scope := record.Str("scope")
	return scope != "" && !strings.HasPrefix(scope, "none")
}
