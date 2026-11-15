package usage

import (
	"fmt"
	"os"
	"path/filepath"
	"slices"
	"strings"
	"testing"

	"agentkit/internal/config"
)

// TestMain answers this test program started as `ak adapter`, as a refresh asks a harness's own
// verbs: each ask's words and the account its environment names kept in $HOME/asked, and a 401
// counting 3 resets printed, which one line also says yes to `auth`.
func TestMain(m *testing.M) {
	if len(os.Args) > 1 && os.Args[1] == "adapter" {
		kept, err := os.OpenFile(filepath.Join(os.Getenv("HOME"), "asked"), os.O_WRONLY|os.O_APPEND|os.O_CREATE, 0o600)
		if err == nil {
			fmt.Fprintln(kept, strings.Join(os.Args[1:], " ")+" on "+os.Getenv("AGENTKIT_ACCOUNT"))
			kept.Close()
		}
		fmt.Println(`{"meters": [], "error": "unknown: HTTP 401 from acme", "resets": 3}`)
		os.Exit(0)
	}
	os.Exit(m.Run())
}

// Where no $AGENTKIT_ADAPTER_DIR is named, a refresh asks Claude, whose `usage` is Go's own, through
// this program's `ak adapter` alone, no script needed: `usage`, `auth`, and `reset-status` where
// the answer counts no resets, on the account read, the answer's own count kept.  A harness with no
// such verb, and a read of the folder named, still ask the script.
func TestARefreshAsksAHarnessOwnUsageVerbInItsScriptsPlace(t *testing.T) {
	home := t.TempDir()
	t.Setenv("HOME", home)
	t.Setenv("USERPROFILE", home)
	t.Setenv("AGENTKIT_ADAPTER_DIR", "")
	toml := "[models.anvil]\nharness='claude'\nmodel='claude-anvil-1'\neffort='high'\nprovider='acme'\n" +
		"[models.bale]\nharness='codex'\nmodel='bale-1'\neffort='high'\nprovider='brine'\n" +
		"[providers.acme]\nmode='subscription'\naccounts=['default','two']\n[providers.brine]\nmode='subscription'\n"
	if err := os.MkdirAll(filepath.Join(home, ".agentkit"), 0o700); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(home, ".agentkit", "config.toml"), []byte(toml), 0o600); err != nil {
		t.Fatal(err)
	}
	program, _, err := config.Running()
	if err != nil {
		t.Fatal(err)
	}
	own := []string{program, "adapter", filepath.Dir(filepath.Dir(program)), "claude"}
	sources, err := listed(true)
	if err != nil {
		t.Fatal(err)
	}
	for _, src := range sources {
		if src.Harness == "codex" {
			if len(src.adapter) != 1 {
				t.Errorf("codex is asked with %q", src.adapter)
			}
			continue
		}
		if !slices.Equal(src.adapter, own) || src.broken != nil {
			t.Fatalf("claude is asked with %q (%v)", src.adapter, src.broken)
		}
		if src.account != "two" {
			continue
		}
		probed := probe(src, clock())
		if count, _ := number(probed.Get("resets")); count != 3 || probed.Get("logged_in") != true {
			t.Errorf("probed %v", probed)
		}
		if src.resets(nil) != nil {
			t.Errorf("reset-status counted what it never said")
		}
	}
	data, _ := os.ReadFile(filepath.Join(home, "asked"))
	asked := strings.Join(own[1:], " ")
	if want := []string{asked + " usage on two", asked + " auth on two", asked + " reset-status on two"}; !slices.Equal(strings.Split(strings.TrimSpace(string(data)), "\n"), want) {
		t.Errorf("asked %q, not %q", data, want)
	}
	t.Setenv("AGENTKIT_ADAPTER_DIR", filepath.Join(home, "adapters"))
	if sources, _ = listed(true); len(sources) == 0 || len(sources[0].adapter) != 1 {
		t.Errorf("a folder named still asks its own verb: %+v", sources)
	}
}
