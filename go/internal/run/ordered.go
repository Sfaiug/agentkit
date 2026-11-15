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

// LoopDeath is transitions.loop_death: the last death where it ended the loop the record names now,
// else nil.  A resume starts a new loop and leaves the deaths as they were, so one of another pid,
// or noted before this loop started (a pid comes round again), is an earlier loop's.
func LoopDeath(record *Object) *Object {
	deaths := record.List("deaths")
	if len(deaths) == 0 {
		return nil
	}
	death, ok := deaths[len(deaths)-1].(*Object)
	if !ok || !Equal(death.Get("pid"), record.Get("pid")) {
		return nil
	}
	at, dated := death.Num("at")
	if identity := record.Dict("process_identity"); identity != nil && dated {
		if start, ok := identity.Num("started_at"); ok && at < start {
			return nil
		}
	}
	return death
}

// Scoped is whether a unit the manager holds ran that loop (turns.scope_is_real).
func Scoped(record *Object) bool {
	scope := record.Str("scope")
	return scope != "" && !strings.HasPrefix(scope, "none")
}
