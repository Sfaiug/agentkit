package run

import "time"

// NeedsLook is Python's menu.v5o_needs_look: an ending still the owner's, rather than
// its seat's, until acknowledged, replaced or aged out.
func (index Index) NeedsLook(record *Object, now time.Time) bool {
	state := record.Str("state")
	if record.Truthy("recovery_acknowledged_at") || (state == "error" || state == "exhausted") && Going(record, now) {
		return false
	}
	if state == "exhausted" {
		return !index.replaced(record, "merged-from")
	}
	if record.Truthy("handed_back") || record.Truthy("handback_pending") || record.Truthy("merged") ||
		!Failed(record) && state != "interrupted" && state != "pass" {
		return false
	}
	ended, dated := record.Num(firstKey(record, "finished_at", "interrupted_at", "started_at"))
	if dated && seconds(now)-ended > GCAge || index.superseded(record) {
		return false
	}
	return state != "pass" || record.Truthy("repo") && !record.Truthy("no_merge") &&
		!record.Truthy("review_pr") && !record.Truthy("review_posted")
}
