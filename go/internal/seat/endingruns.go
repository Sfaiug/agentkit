package seat

import (
	"fmt"
	"time"

	"agentkit/internal/run"
)

// Decision endings need no cleanup to be read. A recovery notice already handed to its
// seat is settled too; other recovery reads remain Python's.
func decisionRun(record *run.Object) (runView, bool) {
	if run.Ended(record) && record.Str("state") != "error" && !record.Truthy("merged") && record.Str("state") != "not_needed" {
		return runView{}, true
	}
	settled := record.Truthy("handback_pending") || record.Truthy("handed_back") || record.Truthy("recovery_notified") || record.Truthy("recovery_acknowledged_at")
	return runView{}, record.Str("state") == "interrupted" && settled
}

func endingNews(facts climbing) (*answer, error) {
	if facts.found.authority == "" || facts.found.state != "at_prompt" && facts.found.state != "draft" {
		return nil, nil
	}
	for _, each := range facts.mine {
		if !run.OwesEnding(each.record, time.Unix(0, int64(facts.now*1e9))) {
			continue
		}
		recorded, pending := EndingDelivery(each.record, each.census, facts.name)
		if !recorded && (!pending || each.record.Truthy("handback_typed")) {
			return &answer{word: "working", reason: fmt.Sprintf("telling it how run %s ended", each.name), since: facts.found.began}, nil
		}
	}
	return nil, nil
}
