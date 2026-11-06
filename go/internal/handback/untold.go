package handback

import "agentkit/internal/run"

// Untold is whether a stop that needs recovery is nobody's news, Python's notify_recovery: a run
// exhausted on a provider's window resumes itself once it refills.
func Untold(record *run.Object) bool {
	return record.Str("state") == "exhausted" && record.Truthy("quota_dry")
}
