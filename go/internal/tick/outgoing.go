package tick

import "agentkit/internal/run"

// A foreign run keeps its PR after it leaves the open search. Python's own_prs follows
// that saved URL and delivers the maintainer's decision, which Go does not carry yet.
func noSavedForeignPRs() bool {
	return run.Every(func(_ string, record *run.Object) bool {
		return !record.Truthy("foreign") || !record.Truthy("pr")
	})
}
