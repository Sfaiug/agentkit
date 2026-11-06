package harness

import (
	"os"
	"path/filepath"
	"testing"

	"agentkit/internal/config"
)

// The login asked about is the one read, whatever account the caller's own seat is on.
func TestMuseAuthReadsTheLoginItIsAskedAbout(t *testing.T) {
	home := t.TempDir()
	t.Setenv("HOME", home)
	t.Setenv("USERPROFILE", home)
	t.Setenv("AGENTKIT_ACCOUNT", "second") // the caller's seat's
	t.Setenv("XDG_CONFIG_HOME", filepath.Join(home, ".muse-second"))
	t.Setenv("META_API_KEY", "")
	t.Setenv("AGENTKIT_MUSE_PROVIDER", "")
	usual := filepath.Join(home, ".config", "muse", "auth.json")
	if err := os.MkdirAll(filepath.Dir(usual), 0o700); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(usual, []byte(`{"token": "acme"}`), 0o600); err != nil {
		t.Fatal(err)
	}
	if answer := museAuth(config.Login{}, false); !answer.Yes {
		t.Fatal("the usual login was read off the caller's account:", answer.Line)
	}
	if answer := museAuth(config.Login{Account: "second"}, true); answer.Yes {
		t.Fatal("an account with no login of its own read as logged in:", answer.Line)
	}
}
