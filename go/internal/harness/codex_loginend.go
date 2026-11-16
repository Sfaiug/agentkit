package harness

import (
	"io"
	"os"
	"path/filepath"

	"agentkit/internal/run"
)

func init() {
	verbs["codex login-end"] = codexLoginEnd
}

// codexLoginEnd is adapters/codex.sh's `login-end`: whose the login is and the ChatGPT plan, as
// its id token names them; its end null, as Codex renews its access token with a refresh token
// that names none, and a login that dies shows only once `auth` says so.
func codexLoginEnd(_ []string, out, _ io.Writer) int {
	data, _ := os.ReadFile(filepath.Join(codexLogin(), "auth.json"))
	auth, _ := run.Decode(data)
	tokens, _ := index(auth, "tokens")
	token, _ := index(tokens, "id_token")
	text, _ := token.(string)
	claims := codexClaims(text)
	plan, _ := index(claims.Get("https://api.openai.com/auth"), "chatgpt_plan_type")
	named, _ := plan.(string)
	return loginEnd(out, claims.Str("email"), nil, named)
}
