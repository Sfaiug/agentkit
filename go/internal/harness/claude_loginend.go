package harness

import (
	"fmt"
	"io"
	"math"
	"regexp"

	"agentkit/internal/config"
)

func init() {
	verbs["claude login-end"] = claudeLoginEnd
}

// multiple is the multiple a rate-limit tier ends in, `20x` of `default_claude_max_20x`.
var multiple = regexp.MustCompile(`_([0-9]+x)$`)

// claudeLoginEnd is adapters/claude.sh's `login-end`, for the login $AGENTKIT_ACCOUNT names, read
// and never renewed: whose it is; the epoch second its refresh token dies, `refreshTokenExpiresAt`,
// which no renewal moves and which is milliseconds past eleven digits; and its plan, the login's
// `subscriptionType` with the multiple its `rateLimitTier` ends in: `max 20x`, `pro`.
func claudeLoginEnd(_ []string, out, errOut io.Writer) int {
	login, _, err := config.Account("claude")
	if err != nil {
		fmt.Fprintf(errOut, "ak adapter: %s\n", err)
		return 2
	}
	_, _, oauth := claudeLogin(login)
	var ends any
	if end, ok := oauth.Num("refreshTokenExpiresAt"); ok {
		if end > 99999999999 {
			end = math.Floor(end / 1000)
		}
		ends = end
	}
	plan := oauth.Str("subscriptionType")
	if tier := multiple.FindStringSubmatch(oauth.Str("rateLimitTier")); plan != "" && tier != nil {
		plan += " " + tier[1]
	}
	return loginEnd(out, claudeEmail(login), ends, plan)
}
