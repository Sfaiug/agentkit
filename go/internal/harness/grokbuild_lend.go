package harness

import (
	"time"

	"agentkit/internal/config"
	"agentkit/internal/run"
)

// grokLend lends Grok Build's login as grokbuild.sh's `lend` does: every entry without its
// refresh token, so grok runs a turn on a key until its `expires_at`, the latest where several
// are.
func grokLend(login config.Login) Loan {
	file, _, value, entries := grokLogin(login)
	var ends int64
	for _, entry := range entries {
		if at, ok := grokEnds(entry.Str("expires_at")); ok && grokKeyed(entry) {
			ends = max(ends, at)
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

// grokEnds is the epoch second an `expires_at` names, read as grokbuild.sh's `lend` reads it: to
// the second, any fraction dropped, at UTC or an offset written with or without its colon.
func grokEnds(text string) (int64, bool) {
	for _, layout := range []string{time.RFC3339, "2006-01-02T15:04:05Z0700"} {
		if at, err := time.Parse(layout, text); err == nil {
			return at.Unix(), true
		}
	}
	return 0, false
}
