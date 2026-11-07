package seat

import "agentkit/internal/run"

// Decision endings need no cleanup to be read. A recovery notice already handed to its
// seat is settled too; other recovery reads remain Python's.
func decisionRun(record *run.Object) (runView, bool) {
	if run.Ended(record) && record.Str("state") != "error" && !record.Truthy("merged") && record.Str("state") != "not_needed" {
		return runView{}, true
	}
	settled := record.Truthy("handback_pending") || record.Truthy("handed_back") || record.Truthy("recovery_notified") || record.Truthy("recovery_acknowledged_at")
	return runView{}, record.Str("state") == "interrupted" && settled
}
