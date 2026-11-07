package harness

import (
	"encoding/base64"
	"os"
	"path/filepath"
	"testing"

	"agentkit/internal/config"
)

// `auth` answers as adapters/codex.sh's, line for line, from the login's own auth.json.
func TestCodexAuthReadsTheLoginsAuthJSON(t *testing.T) {
	home := t.TempDir()
	t.Setenv("HOME", home)
	t.Setenv("AGENTKIT_ACCOUNT", "")
	t.Setenv("CODEX_HOME", home+"/.codex-work") // an account's, handed down: never the usual login's
	path := filepath.Join(home, ".codex", "auth.json")
	os.MkdirAll(filepath.Dir(path), 0o700)
	claims := base64.RawURLEncoding.EncodeToString([]byte(`{"email":"ada@acme.test"}`))
	for _, each := range []struct {
		name, auth string
		yes        bool
		line       string
	}{
		{"no file", "", false, "codex: no " + path + "; run `codex login`"},
		{"no token", `{"tokens": {"access_token": ""}}`, false, "codex: " + path + " carries no access token; run `codex login`"},
		{"no expiry", `{"tokens": {"access_token": "t", "id_token": "h.` + claims + `.s"}}`, true,
			"codex: " + path + " is present and records no expiry; logged in as ada@acme.test"},
		{"an expiry to come, in milliseconds", `{"tokens": {"access_token": "t", "expires_at": 4102444800000}}`, true,
			"codex: the token in " + path + " is still valid"},
		{"an expiry gone", `{"access_token": "t", "expires_at": 1000}`, false, "codex: the token in " + path + " expired; run `codex login`"},
		{"an expiry nobody reads", `{"tokens": {"access_token": "t", "expires_at": "soon"}}`, false,
			"codex: the expiry in " + path + " cannot be read; run `codex login`"},
	} {
		os.Remove(path)
		if each.auth != "" {
			os.WriteFile(path, []byte(each.auth), 0o600)
		}
		if answer := codexAuth(config.Login{}, true); answer.Yes != each.yes || answer.Line != each.line {
			t.Errorf("%s: %+v", each.name, answer)
		}
	}
	t.Setenv("AGENTKIT_ACCOUNT", "work")
	if answer := codexAuth(config.Login{}, true); answer.Yes || answer.Line != "codex: no "+home+"/.codex-work/auth.json; run `codex login`" {
		t.Errorf("an account answered on another login: %+v", answer)
	}
}
