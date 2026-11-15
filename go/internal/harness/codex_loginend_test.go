package harness

import (
	"bytes"
	"encoding/base64"
	"os"
	"path/filepath"
	"testing"
)

// `login-end` answers as adapters/codex.sh's, line for line, from the auth.json of the login
// $AGENTKIT_ACCOUNT names: the email and ChatGPT plan its id token names, each null where it names
// none, and never an end.
func TestCodexLoginEndReadsTheLoginsIDToken(t *testing.T) {
	home := t.TempDir()
	t.Setenv("HOME", home)
	t.Setenv("CODEX_HOME", "")
	jwt := func(claims string) string {
		return `{"tokens": {"access_token": "t", "id_token": "e30.` + base64.RawURLEncoding.EncodeToString([]byte(claims)) + `.s"}}`
	}
	for _, each := range []struct{ account, auth, said string }{
		{"", jwt(`{"email": "owner@acme.test", "https://api.openai.com/auth": {"chatgpt_plan_type": "plus"}}`),
			`{"email":"owner@acme.test","ends":null,"plan":"plus"}`},
		{"", jwt(`{"email": "owner@acme.test", "https://api.openai.com/auth": {"chatgpt_plan_type": ""}}`),
			`{"email":"owner@acme.test","ends":null,"plan":null}`},
		{"", `{"tokens": {"access_token": "t"}}`, `{"email":null,"ends":null,"plan":null}`},
		{"b2", jwt(`{"email": "two@acme.test", "https://api.openai.com/auth": "pro"}`),
			`{"email":"two@acme.test","ends":null,"plan":null}`},
	} {
		t.Setenv("AGENTKIT_ACCOUNT", each.account)
		folder := ".codex"
		if each.account != "" {
			folder += "-" + each.account
		}
		path := filepath.Join(home, folder, "auth.json")
		os.MkdirAll(filepath.Dir(path), 0o700)
		os.WriteFile(path, []byte(each.auth), 0o600)
		var out, errOut bytes.Buffer
		if code := Verb("codex", "login-end")(nil, &out, &errOut); code != 0 || out.String() != each.said+"\n" {
			t.Errorf("%s: exit %d, %q %q", each.auth, code, out.String(), errOut.String())
		}
	}
}
