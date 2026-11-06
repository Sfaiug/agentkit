package loop

import "agentkit/internal/run"

// Unstarted is whether the run is a launch whose receipt still waits in the queue with no driver,
// which Go's resume replays anew from the options it was launched with, where they stand
// (launch.launchStands).  An old receipt with none, one whose repository its launch never settled,
// and one on a road Go does not drive are Python's.
func Unstarted(record *run.Object) bool {
	if record.Str("state") != "queued" || !record.Truthy("slot_waiting") || record.Truthy("worktree") ||
		record.Dict("launch_opts") == nil || !record.Truthy("repo") && !record.Has("scratch") || !unitless(record) {
		return false
	}
	for _, key := range pythonRoads {
		if record.Truthy(key) {
			return false
		}
	}
	return true
}
