package harness

import (
	"bytes"
	"os"
	"path/filepath"
	"runtime"
	"testing"
)

// `logout` signs out the login $AGENTKIT_ACCOUNT names alone, as adapters/claude.sh does: its worker
// token gone, then Claude Code's own sign-out on its directory, with no worker token, its exit the
// verb's; where no login is there, nothing runs and it exits 0.  A `$` in the home's name is a
// letter of it, as the script reads it.
func TestClaudeLogoutSignsOutTheNamedLoginAlone(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("the fake Claude Code is a shell script")
	}
	home := filepath.Join(t.TempDir(), "acme$HOME")
	t.Setenv("HOME", home)
	t.Setenv("PATH", filepath.Join(home, "bin"))
	t.Setenv("CLAUDE_CODE_OAUTH_TOKEN", "worker")
	t.Setenv("CLAUDE_CONFIG_DIR", "")
	write := func(path, text string) string {
		path = filepath.Join(home, path)
		os.MkdirAll(filepath.Dir(path), 0o700)
		os.WriteFile(path, []byte(text), 0o700)
		return path
	}
	write("bin/claude", "#!/bin/sh\necho \"$* $CLAUDE_CONFIG_DIR ${CLAUDE_CODE_OAUTH_TOKEN-none}\" >> \"$HOME/ran\"\nexit 3\n")
	usual := write(".agentkit/secrets/claude_oauth_token", "worker\n")
	named := write(".agentkit/secrets/claude_oauth_token.b2", "worker\n")
	write(".claude-b2/.credentials.json", "{}")
	for _, each := range []struct {
		account string
		code    int
		gone    string
	}{{"b2", 3, named}, {"", 0, usual}} {
		t.Setenv("AGENTKIT_ACCOUNT", each.account)
		var out, errOut bytes.Buffer
		if code := Verb("claude", "logout")(nil, &out, &errOut); code != each.code {
			t.Errorf("%q: exit %d, %q", each.account, code, errOut.String())
		}
		if _, err := os.Stat(each.gone); err == nil {
			t.Errorf("%q: %s is still there", each.account, each.gone)
		}
	}
	if ran, _ := os.ReadFile(filepath.Join(home, "ran")); string(ran) != "auth logout "+filepath.Join(home, ".claude-b2")+" none\n" {
		t.Errorf("Claude Code ran: %q", ran)
	}
}

// The token goes as the script's `rm -f` takes it: a directory in its place stays, and the verb
// exits 1 with the login still signed in; under a secrets folder that is a file, the token is
// as absent as one not there, and the sign-out runs.
func TestClaudeLogoutRemovesTheTokenAsRmF(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("the fake Claude Code is a shell script")
	}
	for _, each := range []struct {
		layout string
		code   int
		ran    bool
	}{{"directory", 1, false}, {"parent file", 3, true}} {
		home := t.TempDir()
		t.Setenv("HOME", home)
		t.Setenv("PATH", filepath.Join(home, "bin"))
		t.Setenv("AGENTKIT_ACCOUNT", "")
		t.Setenv("CLAUDE_CONFIG_DIR", filepath.Join(home, "login"))
		os.MkdirAll(filepath.Join(home, "login"), 0o700)
		os.WriteFile(filepath.Join(home, "login/.credentials.json"), []byte("{}"), 0o600)
		os.MkdirAll(filepath.Join(home, "bin"), 0o700)
		os.WriteFile(filepath.Join(home, "bin/claude"), []byte("#!/bin/sh\n: > \"$HOME/ran\"\nexit 3\n"), 0o700)
		token := filepath.Join(home, ".agentkit/secrets/claude_oauth_token")
		if each.layout == "directory" {
			os.MkdirAll(token, 0o700)
		} else {
			os.MkdirAll(filepath.Join(home, ".agentkit"), 0o700)
			os.WriteFile(filepath.Dir(token), []byte("not a directory"), 0o600)
		}
		var out, errOut bytes.Buffer
		if code := Verb("claude", "logout")(nil, &out, &errOut); code != each.code {
			t.Errorf("%s: exit %d, %q", each.layout, code, errOut.String())
		}
		if _, err := os.Stat(filepath.Join(home, "ran")); (err == nil) != each.ran {
			t.Errorf("%s: Claude Code ran: %v", each.layout, err == nil)
		}
		if info, err := os.Stat(token); each.layout == "directory" && (err != nil || !info.IsDir()) {
			t.Errorf("%s: the directory went: %v", each.layout, err)
		}
	}
}
