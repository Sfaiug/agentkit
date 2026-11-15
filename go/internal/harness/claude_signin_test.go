package harness

import (
	"bytes"
	"os"
	"path/filepath"
	"runtime"
	"testing"
)

// `login` answers as adapters/claude.sh's does, for the login $AGENTKIT_ACCOUNT names: 2 where Claude
// Code is not installed, 0 where that login holds an access token unless `again` is asked, and 1
// off a terminal, signing nothing in.  A `$` in its directory's name is a letter of it, as the
// script reads it.
func TestClaudeLoginSignsInOnlyWhereItMay(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("the fake Claude Code is a shell script")
	}
	home := filepath.Join(t.TempDir(), "acme$HOME")
	t.Setenv("HOME", home)
	t.Setenv("PATH", filepath.Join(home, "bin"))
	t.Setenv("CLAUDE_CONFIG_DIR", "")
	stdin, file := os.Stdin, filepath.Join(home, "stdin") // off a terminal, however the test runs
	os.WriteFile(file, nil, 0o600)
	os.Stdin, _ = os.Open(file)
	t.Cleanup(func() { os.Stdin.Close(); os.Stdin = stdin })
	for _, login := range []string{".claude-b2", "usual$HOME"} {
		os.MkdirAll(filepath.Join(home, login), 0o700)
		os.WriteFile(filepath.Join(home, login, ".credentials.json"), []byte(`{"claudeAiOauth":{"accessToken":"x"}}`), 0o600)
	}
	login := func(account string, args ...string) (int, string) {
		t.Setenv("AGENTKIT_ACCOUNT", account)
		t.Setenv("CLAUDE_CONFIG_DIR", "")
		if account == "usual" {
			t.Setenv("AGENTKIT_ACCOUNT", "")
			t.Setenv("CLAUDE_CONFIG_DIR", filepath.Join(home, "usual$HOME"))
		}
		var out, errOut bytes.Buffer
		code := Verb("claude", "login")(args, &out, &errOut)
		return code, out.String() + errOut.String()
	}
	if code, said := login("b2"); code != 2 || said != "claude.sh login: claude is not installed\n" {
		t.Errorf("not installed: exit %d, %q", code, said)
	}
	os.MkdirAll(filepath.Join(home, "bin"), 0o700)
	os.WriteFile(filepath.Join(home, "bin/claude"), []byte("#!/bin/sh\n: > \"$HOME/ran\"\n"), 0o700)
	off := "claude: not logged in; run `claude auth login` in a terminal\n"
	for _, each := range []struct {
		account string
		args    []string
		code    int
		said    string
	}{{"b2", nil, 0, "claude: already logged in\n"}, {"usual", nil, 0, "claude: already logged in\n"},
		{"b2", []string{"again"}, 1, off}, {"", nil, 1, off}} {
		if code, said := login(each.account, each.args...); code != each.code || said != each.said {
			t.Errorf("%q %q: exit %d, %q", each.account, each.args, code, said)
		}
	}
	if _, err := os.Stat(filepath.Join(home, "ran")); err == nil {
		t.Error("Claude Code ran")
	}
}

// `forget` takes a named login's config directory and worker token away, a link in them and never
// what it leads to, and refuses the usual login; under a secrets folder that is a file, the token
// is as absent as one not there.
func TestClaudeForgetTakesTheNamedLoginAway(t *testing.T) {
	home := t.TempDir()
	t.Setenv("HOME", home)
	t.Setenv("CLAUDE_CONFIG_DIR", "")
	write := func(path string) string {
		path = filepath.Join(home, path)
		os.MkdirAll(filepath.Dir(path), 0o700)
		os.WriteFile(path, []byte("{}"), 0o600)
		return path
	}
	usual, settings := write(".agentkit/secrets/claude_oauth_token"), write(".claude/settings.json")
	named := write(".agentkit/secrets/claude_oauth_token.b2")
	write(".claude-b2/.credentials.json")
	if err := os.Symlink(settings, filepath.Join(home, ".claude-b2/settings.json")); err != nil {
		t.Skip("no symbolic links here:", err)
	}
	t.Setenv("AGENTKIT_ACCOUNT", "")
	var errOut bytes.Buffer
	if code := Verb("claude", "forget")(nil, &errOut, &errOut); code != 2 || errOut.String() != "claude.sh forget: the usual login is never forgotten\n" {
		t.Errorf("the usual login: exit %d, %q", code, errOut.String())
	}
	t.Setenv("AGENTKIT_ACCOUNT", "b2")
	if code := Verb("claude", "forget")(nil, &errOut, &errOut); code != 0 {
		t.Errorf("b2: exit %d, %q", code, errOut.String())
	}
	for path, kept := range map[string]bool{filepath.Join(home, ".claude-b2"): false, named: false, usual: true, settings: true} {
		if _, err := os.Lstat(path); (err == nil) != kept {
			t.Errorf("%s there: %v", path, err == nil)
		}
	}
	os.RemoveAll(filepath.Join(home, ".agentkit/secrets"))
	write(".agentkit/secrets")
	write(".claude-b3/.credentials.json")
	t.Setenv("AGENTKIT_ACCOUNT", "b3")
	if code := Verb("claude", "forget")(nil, &errOut, &errOut); code != 0 {
		t.Errorf("b3: exit %d, %q", code, errOut.String())
	}
	if _, err := os.Lstat(filepath.Join(home, ".claude-b3")); err == nil {
		t.Error("b3's directory is still there")
	}
}
