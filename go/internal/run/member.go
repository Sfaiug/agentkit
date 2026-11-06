package run

import (
	"os"
	"strings"
)

// Member is whether a record holds a place in its landing line, Python's land.member, the one
// answer the line, what a red waits on, the lander's wake and the record's line_since read: it
// waits there, or it is a green delivery that has not ended, is on its way
// (handback.followup_open) and runs or is resumed by the tick.
func Member(record *Object) bool {
	wait := record.Dict("waiting_on")
	if wait == nil || record.Truthy("merged") {
		return false
	}
	_, joined := wait.Get("joined").(Number)
	if _, line := wait.Get("line").(string); !line || !joined {
		return false
	}
	if record.Str("state") == "waiting" {
		return true
	}
	if !wait.Has("land") || wait.Has("fix") || Ended(record) {
		return false
	}
	return delivering(record) && (ProcessActive(record) || TickResumes(record))
}

// delivering is handback.followup_open for a record that has not ended and is not waiting.
func delivering(record *Object) bool {
	switch record.Str("state") {
	case "running", "waiting_login":
		return true
	case "queued":
		return ProcessActive(record) || record.Truthy("slot_waiting")
	case "exhausted":
		// transitions.exhausted_wait: the tick brings it back on a provider's window or a
		// reviewer's, unless a later merged run replaced it
		return !record.Truthy("replaced") &&
			(record.Truthy("quota_dry") || strings.Contains(record.Str("error"), "API/transport errors"))
	case "interrupted":
		return record.Truthy("deaths") && TickResumes(record)
	}
	return false
}

// TickResumes is whether the tick carries a dead loop on itself, Python's
// transitions.tick_resumes: one it has not given up on, with its worktree still there.
func TickResumes(record *Object) bool {
	if deaths := record.List("deaths"); len(deaths) > 0 {
		if last, _ := deaths[len(deaths)-1].(*Object); last != nil && last.Truthy("parked") {
			return false
		}
	}
	info, err := os.Stat(record.Str("worktree"))
	return record.Truthy("worktree") && err == nil && info.IsDir()
}
