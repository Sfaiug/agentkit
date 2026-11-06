package seat

import (
	"path/filepath"
	"strings"
	"testing"
)

// A stop forgets a seat it stopped already at once, never by the sweep: Muse's receipt goes with it.
func TestMuseReceiptGoesWithTheSeatItsStopForgets(t *testing.T) {
	home := sandbox(t)
	write(t, filepath.Join(home, ".agentkit", "config.toml"), testConfig+
		"[models.spark]\nharness='muse'\nmodel='spark'\neffort='high'\nprovider='test'\n")
	token := strings.Repeat("a", 32)
	record(t, home, "acme", map[string]any{"orchestrator": "spark", "workers": []string{"spark"}, "muse_launch": token})
	receipt := stateFile(home, "muse-launch-"+token)
	write(t, filepath.Join(receipt, "session"), "session_1")
	if err := forget(filepath.Join(home, ".agentkit", "state"), "acme", quietly); err != nil {
		t.Fatal(err)
	}
	if left, _ := filepath.Glob(receipt + "*"); len(left) > 0 {
		t.Fatalf("the receipt outlived the seat: %q", left)
	}
}
