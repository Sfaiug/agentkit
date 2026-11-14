package seat

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

func TestMuseReceiptIsReadAtTheListingBoundary(t *testing.T) {
	for name, late := range map[string]bool{"reported already": false, "reports while publishing": true} {
		t.Run(name, func(t *testing.T) {
			home := sandbox(t)
			write(t, filepath.Join(home, ".agentkit", "config.toml"), testConfig+
				"[models.spark]\nharness='muse'\nmodel='spark'\neffort='high'\nprovider='test'\n")
			token := strings.Repeat("a", 32)
			record(t, home, "acme", map[string]any{"orchestrator": "spark", "workers": []string{"spark"},
				"muse_launch": token, "id_source": nil})
			receipt := stateFile(home, "muse-launch-"+token)
			drawn(t, home, "acme", "Change approval defaults in /permissions\n")
			before, err := os.ReadFile(stateFile(home, "session-acme.json"))
			if err != nil {
				t.Fatal(err)
			}
			if !late {
				write(t, filepath.Join(receipt, "session"), "session_1")
			}
			listing, known := Looking(time.Now())
			if !known {
				t.Fatal("a seat its launch reported a session for was left to Python")
			}
			if late {
				write(t, filepath.Join(receipt, "session"), "session_1")
			}
			lines, found, err := listing.Explain("acme", time.Now())
			if err != nil || !found {
				t.Fatalf("not explained: %v, %v", found, err)
			}
			if lines[0] != "acme  needs you" || lines[2] != "  authority: screen  rule: asking.approval" {
				t.Fatal(lines)
			}
			if err := listing.Announce(time.Now()); err != nil {
				t.Fatal(err)
			}
			if _, known := Looking(time.Now()); !known {
				t.Fatal("the next listing left a reported session to Python")
			}
			if after, err := os.ReadFile(stateFile(home, "session-acme.json")); err != nil || string(after) != string(before) {
				t.Fatalf("publishing changed Muse's record: %s, %v", after, err)
			}
			if data, err := os.ReadFile(filepath.Join(receipt, "session")); err != nil || string(data) != "session_1" {
				t.Fatalf("the receipt changed: %s, %v", data, err)
			}
		})
	}
}
