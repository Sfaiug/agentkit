package usage

import (
	"os"
	"path/filepath"
	"testing"

	"agentkit/internal/config"
	"agentkit/internal/run"
)

func TestAReadingOfALoginConfigNoLongerListsLeavesTheSnapshotAlone(t *testing.T) {
	home := t.TempDir()
	t.Setenv("HOME", home)
	t.Setenv("USERPROFILE", home)
	if err := os.MkdirAll(state(), 0o700); err != nil {
		t.Fatal(err)
	}
	listed := "[models.anvil]\nharness='echo'\nmodel='anvil-1'\neffort='high'\nprovider='acme'\n" +
		"[providers.acme]\nmode='subscription'\naccounts=['default','two']\n"
	if err := os.WriteFile(filepath.Join(home, ".agentkit", "config.toml"), []byte(listed), 0o600); err != nil {
		t.Fatal(err)
	}
	now := clock()
	week := func(used float64) *run.Object {
		return fields("meters", []any{fields("name", "weekly", "used", used, "window_secs", 604800, "resets_at", now+86400)})
	}
	held := fields("acme", fields("accounts", fields("default", week(30), "two", week(70))))
	if err := os.WriteFile(filepath.Join(state(), "usage.json"), []byte(run.Line(fields("fetched_at", now, "providers", held))), 0o600); err != nil {
		t.Fatal(err)
	}
	acme := config.Subscription{Name: "acme"}
	for _, src := range []source{{Subscription: acme}, {Subscription: acme, account: "three"}} {
		patch(src, week(10))
		if got := object(read()).Get("providers"); run.Line(got) != run.Line(held) {
			t.Fatalf("login %q rewrote the snapshot: %s", src.account, run.Line(got))
		}
	}
}
