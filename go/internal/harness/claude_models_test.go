package harness

import (
	"bytes"
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"testing"
)

// claudeAPI is a HOME whose curl is Anthropic's models API, answering `page` for the first page and
// `page-<id>` for the one after that id, failing where there is no such file, and logging each ask:
// its words, then what came down its stdin.  Its `security` holds no Keychain entry.
func claudeAPI(t *testing.T) (home string, write func(path, text string)) {
	t.Helper()
	if runtime.GOOS == "windows" {
		t.Skip("the fake curl is a shell script")
	}
	home = t.TempDir()
	write = func(path, text string) {
		path = filepath.Join(home, path)
		os.MkdirAll(filepath.Dir(path), 0o700)
		os.WriteFile(path, []byte(text), 0o700)
	}
	write("bin/curl", `#!/bin/sh
printf '%s\n' "$@" >> "$HOME/asked"
cat >> "$HOME/asked"
for url; do :; done
case $url in
*after_id=*) cat "$HOME/page-${url##*after_id=}" ;;
*) cat "$HOME/page" ;;
esac
`)
	write("bin/security", "#!/bin/sh\nexit 44\n")
	for key, value := range map[string]string{"HOME": home, "AGENTKIT_ADAPTER_DIR": "", "AGENTKIT_ACCOUNT": "",
		"CLAUDE_CONFIG_DIR": "", "CLAUDE_CODE_OAUTH_TOKEN": "", "ANTHROPIC_BASE_URL": "",
		"PATH": filepath.Join(home, "bin") + string(os.PathListSeparator) + os.Getenv("PATH")} {
		t.Setenv(key, value)
	}
	return home, write
}

// asked is each ask the fake API was sent since the last, its log then emptied.
func asked(t *testing.T, home string) string {
	t.Helper()
	log, _ := os.ReadFile(filepath.Join(home, "asked"))
	os.Remove(filepath.Join(home, "asked"))
	return string(log)
}

// `models` answers as adapters/claude.sh does: every page of the API in turn, a dated id the
// table knows undated as the table's, the label without `Claude `, and the efforts supported in
// the API's order or `none`; 1, saying nothing, where an ask fails, the shape is not the API's,
// or nothing is listed.
func TestClaudeModelsListsEveryPageAsItsScript(t *testing.T) {
	home, write := claudeAPI(t)
	t.Setenv("ANTHROPIC_BASE_URL", "http://acme.test")
	t.Setenv("CLAUDE_CODE_OAUTH_TOKEN", "sk-ant-oat01-acme")
	write("page", `{"data": [
  {"type": "model", "id": "claude-haiku-4-5-20251001", "display_name": "Claude Haiku 4.5",
   "capabilities": {"effort": {"supported": false, "low": {"supported": true}}}},
  {"id": "claude-nova-9-20990101", "display_name": "Claude Nova 9", "capabilities": {"effort": {
   "supported": true, "max": {"supported": true}, "high": {"supported": false}, "low": {"supported": true}}}}],
 "has_more": true, "last_id": "m2"}`)
	write("page-m2", `{"data": [{"id": "claude-vega-3", "capabilities": null}], "has_more": false, "last_id": "m3"}`)
	var out, errOut bytes.Buffer
	if code := Verb("claude", "models")(nil, &out, &errOut); code != 0 {
		t.Fatalf("exit %d: %q", code, errOut.String())
	}
	if want := "claude-haiku-4-5\tHaiku 4.5\tnone\nclaude-nova-9-20990101\tNova 9\tmax low\nclaude-vega-3\tclaude-vega-3\tnone\n"; out.String() != want {
		t.Errorf("listed %q", out.String())
	}
	words := "-sf\n-H\n@-\n-H\nanthropic-beta: oauth-2025-04-20\n-H\nanthropic-version: 2023-06-01\nhttp://acme.test/v1/models?limit=1000"
	if got, want := asked(t, home), words+"\nAuthorization: Bearer sk-ant-oat01-acme\n"+
		words+"&after_id=m2\nAuthorization: Bearer sk-ant-oat01-acme\n"; got != want {
		t.Errorf("asked %q, not %q", got, want)
	}
	for _, each := range []struct{ name, file, page string }{{"a failed ask", "page-m2", ""},
		{"nothing listed", "page", `{"data": []}`}, {"an id no string", "page", `{"data": [{"id": 7}]}`},
		{"efforts no object", "page", `{"data": [{"id": "m", "capabilities": {"effort": "max"}}]}`}} {
		os.Remove(filepath.Join(home, each.file))
		if each.page != "" {
			write(each.file, each.page)
		}
		out.Reset()
		if code := Verb("claude", "models")(nil, &out, &errOut); code != 1 || out.Len() != 0 {
			t.Errorf("%s: exit %d, %q", each.name, code, out.String())
		}
	}
}

// The token is the login's own, as the script finds it: the worker token from the environment,
// else from its file, else the seat's login; a named account's alone, never the usual login's;
// with none, nothing is asked and it exits 1.
func TestClaudeModelsAsksWithTheLoginsOwnToken(t *testing.T) {
	home, write := claudeAPI(t)
	write("page", `{"data": [{"id": "claude-vega-3"}]}`)
	write(".agentkit/secrets/claude_oauth_token", "file\n\n")
	write(".claude/.credentials.json", `{"claudeAiOauth": {"accessToken": "seat"}}`)
	write(".agentkit/secrets/claude_oauth_token.b2", "b2-file\n")
	write(".claude-b2/.credentials.json", `{"claudeAiOauth": {"accessToken": "b2-seat"}}`)
	for _, each := range []struct{ account, env, gone, bearer string }{
		{"", "env", "", "env"},
		{"", "", "", "file"},
		{"", "", ".agentkit/secrets/claude_oauth_token", "seat"},
		{"b2", "env", "", "b2-file"},
		{"b2", "env", ".agentkit/secrets/claude_oauth_token.b2", "b2-seat"},
		{"b2", "env", ".claude-b2/.credentials.json", ""},
	} {
		t.Setenv("AGENTKIT_ACCOUNT", each.account)
		t.Setenv("CLAUDE_CODE_OAUTH_TOKEN", each.env)
		if each.gone != "" {
			os.Remove(filepath.Join(home, each.gone))
		}
		var out, errOut bytes.Buffer
		code := Verb("claude", "models")(nil, &out, &errOut)
		said := asked(t, home)
		if each.bearer == "" {
			if code != 1 || said != "" {
				t.Errorf("%q with no token: exit %d, asked %q", each.account, code, said)
			}
			continue
		}
		if code != 0 || !strings.HasSuffix(said, "https://api.anthropic.com/v1/models?limit=1000\nAuthorization: Bearer "+each.bearer+"\n") {
			t.Errorf("%q, %s gone: exit %d %q, asked %q", each.account, each.gone, code, errOut.String(), said)
		}
	}
}

// Where PATH finds no claude, the script's preamble puts ~/.local/bin, claude's installer's folder,
// ahead of PATH, so the curl there asks; where PATH finds claude, PATH's own curl does.
func TestClaudeModelsAsksTheCurlItsScriptFinds(t *testing.T) {
	home, write := claudeAPI(t)
	t.Setenv("CLAUDE_CODE_OAUTH_TOKEN", "acme")
	t.Setenv("PATH", filepath.Join(home, "path"))
	write("path/curl", "#!/bin/sh\necho '{\"data\": [{\"id\": \"on-path\"}]}'\n")
	write(".local/bin/curl", "#!/bin/sh\necho '{\"data\": [{\"id\": \"local\"}]}'\n")
	for _, each := range []struct{ claude, listed string }{{"", "local"}, {"path/claude", "on-path"}} {
		if each.claude != "" {
			write(each.claude, "#!/bin/sh\n")
		}
		var out, errOut bytes.Buffer
		if code := Verb("claude", "models")(nil, &out, &errOut); code != 0 || out.String() != each.listed+"\t"+each.listed+"\tnone\n" {
			t.Errorf("claude at %q: exit %d, %q %q", each.claude, code, out.String(), errOut.String())
		}
	}
}
