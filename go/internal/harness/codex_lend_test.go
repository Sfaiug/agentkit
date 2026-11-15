package harness_test

import (
	"bytes"
	"encoding/base64"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"testing"
	"time"

	"agentkit/internal/adapters"
)

// TestCodexLend: `ak adapter <root> codex lend <home> [own]` is adapters/codex.sh's `lend`, in its
// words and exit codes: the login Codex runs a turn on copied where a turn with HOME=<home> reads
// it, nothing in it renewing, and the second it lapses printed where it does.
func TestCodexLend(t *testing.T) {
	home := t.TempDir()
	for key, value := range map[string]string{"HOME": home, "USERPROFILE": home, "CODEX_HOME": "",
		"AGENTKIT_ACCOUNT": "", "AGENTKIT_ADAPTER_DIR": ""} {
		t.Setenv(key, value)
	}
	token := func(claims string) string {
		return "eyJhbGciOiJub25lIn0." + base64.RawURLEncoding.EncodeToString([]byte(claims)) + ".fixture"
	}
	soon := time.Now().Unix() + 3600
	live := token(`{"exp": ` + strconv.FormatInt(soon, 10) + `}`)
	lent := `{"auth_mode": "chatgpt", "tokens": {"access_token": "` + live + `", "refresh_token": "lent: renews nothing"}}`
	usual, named := filepath.Join(home, ".codex", "auth.json"), filepath.Join(home, ".codex-acme", "auth.json")
	none := func(file string) string {
		return "codex: no unexpired access token or API key in " + file + " to lend; run `codex login`\n"
	}
	for _, each := range []struct {
		name, account, file, login string
		args                       []string
		taken                      bool
		code                       int
		out, errOut, at, copy      string
	}{
		{name: "no home", code: 2, errOut: "codex.sh lend needs <home>\n"},
		{name: "no login", args: []string{"to"}, code: 1, errOut: none(usual)},
		{name: "no object", file: usual, login: `["fixture"]`, args: []string{"to"}, code: 1, errOut: none(usual)},
		{name: "a blank access token", file: usual, login: `{"tokens": {"access_token": " "}}`, args: []string{"to"},
			code: 1, errOut: none(usual)},
		{name: "a lapsed access token", file: usual, args: []string{"to"}, code: 1, errOut: none(usual),
			login: `{"tokens": {"access_token": "` + token(`{"exp": 1}`) + `"}}`},
		{name: "an access token naming no end", file: usual, args: []string{"to"}, code: 1, errOut: none(usual),
			login: `{"tokens": {"access_token": "` + token(`{"exp": "never"}`) + `"}}`},
		{name: "a blank API key", file: usual, login: `{"OPENAI_API_KEY": " ", "tokens": {"access_token": "` + live + `"}}`,
			args: []string{"to"}, code: 1, errOut: none(usual)},
		{name: "a ChatGPT login", file: usual, args: []string{"to"}, out: strconv.FormatInt(soon, 10) + "\n",
			login: `{"auth_mode": "chatgpt", "tokens": {"access_token": "` + live + `", "refresh_token": "fixture"}}`,
			at:    ".codex/auth.json", copy: lent},
		{name: "a ChatGPT login beside an API key", file: usual, args: []string{"to"}, out: strconv.FormatInt(soon, 10) + "\n",
			login: `{"auth_mode": "chatgpt", "OPENAI_API_KEY": "sk-fixture", "tokens": {"access_token": "` + live + `"}}`,
			at:    ".codex/auth.json", copy: `{"auth_mode": "chatgpt", "OPENAI_API_KEY": "sk-fixture", "tokens": {"access_token": "` +
				live + `", "refresh_token": "lent: renews nothing"}}`},
		{name: "an API key", file: usual, login: `{"OPENAI_API_KEY": "sk-fixture", "tokens": null}`, args: []string{"to"},
			at: ".codex/auth.json", copy: `{"OPENAI_API_KEY": "sk-fixture", "tokens": null}`},
		{name: "an API key login keeping tokens", file: usual, args: []string{"to"}, at: ".codex/auth.json",
			login: `{"auth_mode": "apikey", "OPENAI_API_KEY": "sk-fixture", "tokens": {"access_token": "` + token(`{"exp": 1}`) + `"}}`,
			copy: `{"auth_mode": "apikey", "OPENAI_API_KEY": "sk-fixture", "tokens": {"access_token": "` + token(`{"exp": 1}`) +
				`", "refresh_token": "lent: renews nothing"}}`},
		{name: "no named login", account: "acme", file: usual, login: lent, args: []string{"to", "own"}, code: 1,
			errOut: none(named)},
		{name: "a named login, own", account: "acme", file: named, login: lent, args: []string{"to", "own"},
			out: strconv.FormatInt(soon, 10) + "\n", at: ".codex-acme/auth.json", copy: lent},
		{name: "a named login", account: "acme", file: named, login: lent, args: []string{"to"},
			out: strconv.FormatInt(soon, 10) + "\n", at: ".codex/auth.json", copy: lent},
		{name: "this HOME", file: usual, login: lent, args: []string{home}, code: 2,
			errOut: "lend: " + home + " is this HOME; lend into another\n"},
		{name: "a login there already", file: usual, login: lent, args: []string{"to"}, taken: true, code: 2,
			errOut: "lend: <to>/.codex/auth.json is there already; lend into a HOME holding no login\n", at: ".codex/auth.json", copy: "{}"},
	} {
		t.Run(each.name, func(t *testing.T) {
			t.Setenv("AGENTKIT_ACCOUNT", each.account)
			for _, dir := range []string{".codex", ".codex-acme"} {
				os.RemoveAll(filepath.Join(home, dir))
			}
			if each.file != "" {
				os.MkdirAll(filepath.Dir(each.file), 0o700)
				os.WriteFile(each.file, []byte(each.login), 0o600)
			}
			to := t.TempDir()
			if each.taken {
				os.MkdirAll(filepath.Join(to, ".codex"), 0o700)
				os.WriteFile(filepath.Join(to, ".codex", "auth.json"), []byte("{}"), 0o600)
			}
			each.errOut = strings.ReplaceAll(each.errOut, "<to>", to)
			var args []string
			for _, arg := range each.args {
				if arg == "to" {
					arg = to
				}
				args = append(args, arg)
			}
			var out, errOut bytes.Buffer
			if code := adapters.Lend("codex", args, &out, &errOut); code != each.code || out.String() != each.out || errOut.String() != each.errOut {
				t.Fatalf("exit %d, %q, %q; want %d, %q, %q", code, out.String(), errOut.String(), each.code, each.out, each.errOut)
			}
			copied, err := os.ReadFile(filepath.Join(to, each.at))
			if each.at == "" {
				if entries, _ := os.ReadDir(to); len(entries) != 0 {
					t.Fatalf("lent %d files where it lends none", len(entries))
				}
			} else if info, _ := os.Stat(filepath.Join(to, each.at)); err != nil || string(copied) != each.copy || info.Mode().Perm() != 0o600 {
				t.Fatalf("lent %q (%v), want %q, owner-only", copied, err, each.copy)
			}
		})
	}
}
