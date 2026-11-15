package harness

import (
	"os"
	"path/filepath"
	"time"

	"agentkit/internal/config"
	"agentkit/internal/run"
)

// codexLend lends Codex's login as codex.sh's `lend` does: auth.json, on whichever of its two
// logins Codex itself runs a turn, by `auth_mode`, else by an API key being saved there.  A key,
// which no renewal retires, never lapses; an access token lapses at the `exp` it carries.  Where
// the login keeps tokens its refresh token is a placeholder: renewing retires the one used, and
// with no token at all codex sends no credentials.
func codexLend(config.Login) Loan {
	file := filepath.Join(codexLogin(), "auth.json")
	none := Loan{Line: "codex: no unexpired access token or API key in " + file + " to lend; run `codex login`"}
	data, _ := os.ReadFile(file)
	value, _ := run.Decode(data)
	auth, _ := value.(*run.Object)
	if auth == nil {
		return none
	}
	tokens := auth.Dict("tokens")
	mode := auth.Get("auth_mode")
	var ends float64
	if mode == "apikey" || (mode == nil || mode == false) && auth.Get("OPENAI_API_KEY") != nil {
		if key, _ := auth.Get("OPENAI_API_KEY").(string); blank(key) {
			return none
		}
	} else {
		if tokens == nil || blank(tokens.Str("access_token")) {
			return none
		}
		if ends, _ = codexClaims(tokens.Str("access_token")).Num("exp"); ends <= float64(time.Now().Unix()) {
			return none
		}
	}
	if tokens != nil {
		tokens.Set("refresh_token", "lent: renews nothing")
	}
	return Loan{Copy: run.Line(auth), Ends: int64(ends), File: file}
}
