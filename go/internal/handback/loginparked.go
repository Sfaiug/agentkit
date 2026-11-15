package handback

import "agentkit/internal/run"

// LoginParked is whether Python's reap leaves a run parked on a login as it stands: its loop still
// going, or swept already.  notify_recovery tells nobody of one: its login's page is the news.
func LoginParked(record *run.Object) bool {
	return record.Str("state") == "waiting_login" && (run.ProcessActive(record) || swept(record))
}
