package harness

import (
	"fmt"
	"os"
	"path/filepath"
	"testing"
	"time"

	"agentkit/internal/config/adapters"
)

// Python's record_turn: the report leaves the turn's directory for the login's own record, which
// stands as the reading until the meter's window has passed.
func TestAMuseRefusalIsKeptOutsideItsBox(t *testing.T) {
	out, state := t.TempDir(), filepath.Join(t.TempDir(), "state")
	report := filepath.Join(out, adapters.RefusalReport)
	now := float64(time.Now().Unix())
	said := fmt.Sprintf(`{"meters": [{"name": "window", "used": 100, "resets_at": %d, "window_secs": 18000}]}`, int(now)+7200)
	if err := os.WriteFile(report, []byte(said), 0o666); err != nil {
		t.Fatal(err)
	}
	RecordTurn("acme", out, state, "")
	if _, err := os.Stat(report); err != nil {
		t.Fatal("a harness with no such report took it")
	}
	RecordTurn("muse", out, state, "")
	if _, err := os.Stat(report); err == nil {
		t.Fatal("the report stayed to date a later retry")
	}
	if data, err := os.ReadFile(filepath.Join(state, "usage-meta.json")); err != nil || string(data) != said+"\n" {
		t.Fatalf("record %q, %v", data, err)
	}
	if found := UsageRecorded("muse", state, now); len(found) != 1 {
		t.Fatalf("while it stands: %d meters", len(found))
	}
	if found := UsageRecorded("muse", state, now+7200); len(found) != 0 {
		t.Fatalf("past its reset: %d meters", len(found))
	}
	home := t.TempDir()
	t.Setenv("HOME", home)
	t.Setenv("USERPROFILE", home)
	listed := "[models.glint]\nharness='muse'\nmodel='muse-1'\neffort='high'\nprovider='meta'\n" +
		"[providers.meta]\nmode='subscription'\naccounts=['shoal','reef']\n"
	if os.MkdirAll(filepath.Join(home, ".agentkit"), 0o700) != nil || os.WriteFile(filepath.Join(home, ".agentkit", "config.toml"), []byte(listed), 0o600) != nil {
		t.Fatal("no config")
	}
	if found := UsageRecorded("muse", state, now); len(found) != 0 {
		t.Fatalf("the usual login's refusal stood for each listed account: %d meters", len(found))
	}
}
