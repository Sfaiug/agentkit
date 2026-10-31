package harness

import (
	"time"

	"agentkit/internal/config"
	"agentkit/internal/run"
)

// claudeLend lends Claude Code's seat login as claude.sh's `lend` does: its access token alone,
// which runs a turn until `expiresAt`, never its refresh token nor the MCP servers' logins,
// which renew too.  Read, never renewed: a lapsed login is none to lend.
func claudeLend(login config.Login) Loan {
	file, _, oauth := claudeLogin(login)
	ends, dated := claudeEnds(oauth)
	if blank(oauth.Str("accessToken")) || !dated || ends/1000 <= time.Now().Unix() {
		auth, _ := config.Section("claude", "auth")
		remedy, _ := auth["remedy"].(string)
		return Loan{Line: "claude: no unexpired access token in " + file + " to lend; " + remedy}
	}
	oauth.Delete("refreshToken")
	lent := run.NewObject()
	lent.Set("claudeAiOauth", oauth)
	return Loan{Copy: run.Line(lent), Ends: ends / 1000}
}
