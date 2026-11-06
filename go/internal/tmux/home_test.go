package tmux

import (
	"os"
	"path/filepath"
	"testing"
)

// Only the account's own home, however its HOME spells it, names the seats' server: the case
// every person's ak is in, which the keys' scratch HOMEs never are.
func TestOnlyTheAccountsOwnHomeNamesAgentkit(t *testing.T) {
	account, found := passwdHome(os.Getuid())
	if !found {
		t.Skip("this uid has no passwd entry, so no home of its own")
	}
	link := filepath.Join(t.TempDir(), "home")
	if err := os.Symlink(account, link); err != nil {
		t.Fatal(err)
	}
	t.Setenv("AGENTKIT_TMUX_SOCKET", "")
	for _, home := range []string{account, link} {
		t.Setenv("HOME", home)
		if got := Own(); got != "agentkit" {
			t.Errorf("HOME=%s names %q, not the seats' server", home, got)
		}
	}
	t.Setenv("HOME", t.TempDir())
	if got := Own(); got == "agentkit" {
		t.Errorf("a scratch HOME names the seats' server")
	}
}
