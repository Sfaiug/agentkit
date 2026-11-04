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
			// Refusing a listing must precede reconciliation of even an earlier record.
			record(t, home, "aaa", map[string]any{"id_source": nil, "repo": nil})
			token := strings.Repeat("a", 32)
			record(t, home, "acme", map[string]any{"orchestrator": "spark", "workers": []string{"spark"},
				"muse_launch": token, "id_source": nil})
			receipt := stateFile(home, "muse-launch-"+token)
			write(t, filepath.Join(receipt, "lineage"), `{"processes":[],"earlier":[]}`)
			drawn(t, home, "acme", "Change approval defaults in /permissions\n")
			read := func(name string) string {
				t.Helper()
				data, err := os.ReadFile(stateFile(home, name))
				if err != nil {
					t.Fatal(err)
				}
				return string(data)
			}
			before, other := read("session-acme.json"), read("session-aaa.json")
			if !late {
				write(t, filepath.Join(receipt, "session"), "session_1")
			}
			listing, known := Looking(time.Now())
			if known != late {
				t.Fatalf("reported session was not left to Python: known=%v", known)
			}
			if late {
				write(t, filepath.Join(receipt, "session"), "session_1")
				lines, found, err := listing.Explain("acme", time.Now())
				if err != nil || !found {
					t.Fatalf("the report belongs to the next listing: %v, %v", found, err)
				}
				if lines[0] != "acme  needs you" || lines[2] != "  authority: screen  rule: asking.approval" {
					t.Fatal(lines)
				}
				if err := listing.Announce(time.Now()); err != nil {
					t.Fatal(err)
				}
				if _, known := Looking(time.Now()); known {
					t.Fatal("the next listing took a reported session")
				}
			}
			if read("session-acme.json") != before || !late && read("session-aaa.json") != other {
				t.Fatal("publishing changed Muse's record, or handing over reconciled another")
			}
			if data, err := os.ReadFile(filepath.Join(receipt, "session")); err != nil || string(data) != "session_1" {
				t.Fatalf("the receipt changed: %s, %v", data, err)
			}
		})
	}
}
