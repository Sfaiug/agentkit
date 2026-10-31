package harness

import (
	"time"

	"agentkit/internal/config"
	"agentkit/internal/run"
)

// grokLend lends Grok Build's login as grokbuild.sh's `lend` does: every entry without its
// refresh token, so grok runs a turn on a key until its `expires_at`, the latest where several
// are, read to the second in whatever offset from UTC it is written.
func grokLend(login config.Login) Loan {
	file, _, value, entries := grokLogin(login)
	var ends int64
	for _, entry := range entries {
		if at, err := time.Parse(time.RFC3339, entry.Str("expires_at")); err == nil && grokKeyed(entry) {
			ends = max(ends, at.Unix())
		}
	}
	if ends <= time.Now().Unix() {
		return Loan{Line: "grok: no unexpired session key in " + file + " to lend; run `grok login`"}
	}
	for _, entry := range entries {
		entry.Delete("refresh_token")
	}
	return Loan{Copy: run.Line(value), Ends: ends}
}
