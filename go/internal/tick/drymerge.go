package tick

import "agentkit/internal/run"

// toldInside is a merge inside its window that a dry tick's merge checks say nothing of, as
// after_merge_health's dry run reads it: live and told already, at a merge commit its run holds,
// with no deployment to follow.
func toldInside(record *run.Object, now float64) bool {
	return inWindow(record, now) && record.Truthy("live_at") && record.Truthy("live_notified") &&
		!pythons(record, now) && recordedSHA(record) != ""
}
