package handback

import (
	"agentkit/internal/handin"
	"agentkit/internal/run"
)

// ReviewFailed is whether the run's reviewer handed in a FAIL, not a PASS the loop overrode,
// Python's review_failed.
func ReviewFailed(record *run.Object) bool {
	review := &handin.Review{}
	for _, row := range record.List("review_records") {
		if row, ok := row.(*run.Object); ok {
			review.Records = append(review.Records, row)
		}
	}
	return review.Verdict() == "FAIL"
}
