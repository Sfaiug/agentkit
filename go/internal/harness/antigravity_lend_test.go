package harness

import (
	"os"
	"path/filepath"
	"testing"

	"agentkit/internal/config"
)

// `lend` lends the token file whole, never lapsing, as adapters/antigravity.sh's does, and where it
// holds no refresh token says so in that script's words, a named account's own sign-in among them.
func TestAntigravityLendLendsTheTokenFileWhole(t *testing.T) {
	home := t.TempDir()
	t.Setenv("HOME", home)
	usual := filepath.Join(home, ".gemini", "antigravity-cli", "antigravity-oauth-token")
	named := filepath.Join(home, ".gemini", "antigravity-cli-acme", "antigravity-oauth-token")
	none := func(file, signin string) Loan {
		return Loan{Line: "agy: no refresh token in " + file + " to lend; run `" + signin + "` and sign in"}
	}
	login := `{"token": {"access_token": "fixture-access", "refresh_token": "fixture-refresh"}, "id_token_email": "ada@acme.test"}`
	for _, each := range []struct {
		name, account, file, token string
		want                       Loan
	}{
		{"no file", "", usual, "", none(usual, "agy")},
		{"a blank refresh token", "", usual, `{"token": {"refresh_token": " "}}`, none(usual, "agy")},
		{"a token that is no object", "", usual, `{"token": "fixture"}`, none(usual, "agy")},
		{"a login", "", usual, login, Loan{Copy: login, File: usual}},
		{"no named login", "acme", named, "",
			none(named, "DBUS_SESSION_BUS_ADDRESS=disabled: agy --app_data_dir=antigravity-cli-acme")},
		{"a named login", "acme", named, login, Loan{Copy: login, File: named}},
	} {
		os.RemoveAll(filepath.Join(home, ".gemini"))
		if each.token != "" {
			os.MkdirAll(filepath.Dir(each.file), 0o700)
			os.WriteFile(each.file, []byte(each.token), 0o600)
		}
		if got := antigravityLend(config.Login{Account: each.account}); got != each.want {
			t.Errorf("%s: %+v, want %+v", each.name, got, each.want)
		}
	}
}
