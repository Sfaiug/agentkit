package run

import (
	"os"
	"slices"
)

// LoopGone is why a reap or a resume says a loop it found dead stopped.
const LoopGone = "Run process exited or its identity changed."

// LoopDeath is transitions.loop_death, the one reading of whose a death is: the last entry of
// `deaths` where it ended the loop the record names now, else nil.  A resume starts a new loop and
// leaves the deaths as they were, so an entry of another pid, or noted before this loop started
// (`process_identity`), is an earlier loop's: a pid comes round again.  A record naming no start,
// or an entry no time, is read by its pid alone.
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

// TickResumes is whether the tick carries a dead loop on itself, Python's
// transitions.tick_resumes: one whose own death it has not parked, its worktree still there.  A
// park an earlier loop's death carries ended when a resume started the next loop.
func TickResumes(record *Object) bool {
	if ending := LoopDeath(record); ending != nil && ending.Truthy("parked") {
		return false
	}
	info, err := os.Stat(record.Str("worktree"))
	return record.Truthy("worktree") && err == nil && info.IsDir()
}

// Carried is an interruption whose loop's death the tick carries on, so nobody is told of it: a
// reap noticed the death first and recorded it.
func Carried(record *Object) bool {
	return record.Str("state") == "interrupted" && LoopDeath(record) != nil && TickResumes(record)
}

// NoteDeath records the loop's death at now as a reap notes it: once, and only where the tick
// carries it on, so it counts towards the third death in an hour.
func NoteDeath(record *Object, now float64, reason string) {
	if ending := LoopDeath(record); TickResumes(record) && (ending == nil || ending.Truthy("resumed_at")) {
		record.Set("deaths", append(slices.Clone(record.List("deaths")), Fields("at", now, "pid", record.Get("pid"), "reason", reason)))
	}
}
