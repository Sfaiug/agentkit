package usage

import (
	"os"
	"path/filepath"
	"testing"

	"agentkit/internal/config"
	"agentkit/internal/run"
)

// A turn begun on the usual login reports about it after its provider's accounts were added or
// removed: the login is kept under the name config.toml now gives it.
func TestATurnKeepsItsMetersOnTheUsualLoginWhateverItIsNowCalled(t *testing.T) {
	for _, each := range []struct{ before, after, now string }{
		{"", "['default','second']", "default"},
		{"['default']", "", ""},
		{"['named']", "['named']", "named"},
	} {
		home := t.TempDir()
		t.Setenv("HOME", home)
		t.Setenv("USERPROFILE", home)
		adapters, out := filepath.Join(home, "adapters"), filepath.Join(home, "run", "turns", "turn")
		for _, dir := range []string{state(), adapters, out} {
			if err := os.MkdirAll(dir, 0o700); err != nil {
				t.Fatal(err)
			}
		}
		t.Setenv("AGENTKIT_ADAPTER_DIR", adapters)
		configured := func(accounts string) {
			text := "[models.anvil]\nharness='claude'\nmodel='anvil-1'\neffort='high'\nprovider='acme'\n[providers.acme]\nmode='subscription'\n"
			if accounts != "" {
				text += "accounts=" + accounts + "\n"
			}
			if err := os.WriteFile(filepath.Join(home, ".agentkit", "config.toml"), []byte(text), 0o600); err != nil {
				t.Fatal(err)
			}
		}
		event := fields("type", "rate_limit_event", "rate_limit_info", fields("status", "allowed", "unifiedWindows",
			fields("five_hour", fields("utilization", 0.25, "resetsAt", clock()+3600))))
		for path, data := range map[string]string{
			filepath.Join(adapters, "claude.toml"): "version = 1\n",
			filepath.Join(adapters, "claude.sh"):   "#!/bin/sh\nexit 0\n",
			filepath.Join(out, "events.jsonl"):     run.Line(event) + "\n",
		} {
			if err := os.WriteFile(path, []byte(data), 0o700); err != nil {
				t.Fatal(err)
			}
		}
		configured(each.before)
		account, _, err := TurnAccount("anvil", "")
		if err != nil {
			t.Fatal(err)
		}
		configured(each.after)
		Turned(config.Model{Harness: "claude", Provider: "acme"}, account, out)
		src := source{Subscription: config.Subscription{Name: "acme"}, account: each.now}
		if meters := src.cached().List("meters"); len(meters) != 1 || used(object(meters[0])) != 25 {
			t.Fatal(each, run.Line(meters))
		}
	}
}
