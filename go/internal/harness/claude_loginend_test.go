package harness

import (
	"bytes"
	"os"
	"path/filepath"
	"testing"
)

// `login-end` answers as adapters/claude.sh's, line for line, from the login $AGENTKIT_ACCOUNT
// names: its end in seconds however it is written, its plan with its tier's multiple where the
// tier ends in one, and null for what a blob that does not parse cannot say.
func TestClaudeLoginEndReadsTheLoginsOwnFiles(t *testing.T) {
	home := t.TempDir()
	t.Setenv("HOME", home)
	t.Setenv("PATH", t.TempDir()) // no Keychain to read
	t.Setenv("CLAUDE_CONFIG_DIR", "")
	write := func(path, text string) {
		path = filepath.Join(home, path)
		os.MkdirAll(filepath.Dir(path), 0o700)
		os.WriteFile(path, []byte(text), 0o600)
	}
	write(".claude.json", `{"oauthAccount": {"emailAddress": "owner@acme.test"}}`)
	for _, each := range []struct{ account, credentials, said string }{
		{"", `{"claudeAiOauth": {"refreshTokenExpiresAt": 1792470143000, "subscriptionType": "max", "rateLimitTier": "default_claude_max_20x"}}`,
			`{"email":"owner@acme.test","ends":1792470143,"plan":"max 20x"}`},
		{"", `{"claudeAiOauth": {"refreshTokenExpiresAt": 1792470143, "subscriptionType": "pro", "rateLimitTier": "default"}}`,
			`{"email":"owner@acme.test","ends":1792470143,"plan":"pro"}`},
		{"", `{"claudeAiOauth": {"refreshTokenExpiresAt": "soon", "subscriptionType": "", "rateLimitTier": "x_5x"}}`,
			`{"email":"owner@acme.test","ends":null,"plan":null}`},
		{"", `not a login`, `{"email":"owner@acme.test","ends":null,"plan":null}`},
		{"b2", `{"claudeAiOauth": {"subscriptionType": "team"}}`, `{"email":null,"ends":null,"plan":"team"}`},
	} {
		t.Setenv("AGENTKIT_ACCOUNT", each.account)
		folder := ".claude"
		if each.account != "" {
			folder += "-" + each.account
		}
		write(folder+"/.credentials.json", each.credentials)
		var out, errOut bytes.Buffer
		if code := Verb("claude", "login-end")(nil, &out, &errOut); code != 0 || out.String() != each.said+"\n" {
			t.Errorf("%s: exit %d, %q %q", each.credentials, code, out.String(), errOut.String())
		}
	}
}
