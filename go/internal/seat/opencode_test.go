package seat

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

const opencodeConfig = testConfig + "[models.vela]\nharness='opencode'\nmodel='vela'\neffort='high'\nprovider='test'\n"

func TestOpenCodeReceiptIsReadAtTheListingBoundary(t *testing.T) {
	for name, late := range map[string]bool{"reported already": false, "reports while publishing": true} {
		t.Run(name, func(t *testing.T) {
			home := sandbox(t)
			write(t, filepath.Join(home, ".agentkit", "config.toml"), opencodeConfig)
			// The session's database is being written into, which is Python's to read.
			t.Setenv("XDG_DATA_HOME", filepath.Join(home, "share"))
			write(t, filepath.Join(home, "share", "opencode", "opencode.db"), "pages")
			write(t, filepath.Join(home, "share", "opencode", "opencode.db-wal"), "pages it has yet to take in")
			// An earlier record needs reconciliation: handing over must precede every write.
			record(t, home, "aaa", map[string]any{"id_source": nil, "repo": nil})
			token := strings.Repeat("a", 32)
			record(t, home, "acme", map[string]any{"orchestrator": "vela", "workers": []string{"vela"},
				"opencode_launch": token, "id_source": nil})
			receipt := stateFile(home, "opencode-launch-"+token)
			write(t, filepath.Join(receipt, "title-request.json"), `{"title":"acme","id":"request"}`)
			drawn(t, home, "acme", "Permission required\nAllow once\nEnter confirm\n")
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
				write(t, filepath.Join(receipt, "session"), "ses_A012z\n")
			}
			listing, known := Looking(time.Now())
			if known != late {
				t.Fatalf("reported session was not left to Python: known=%v", known)
			}
			if late {
				write(t, filepath.Join(receipt, "session"), "ses_A012z\n")
				lines, found, err := listing.Explain("acme", time.Now())
				if err != nil || !found {
					t.Fatalf("the report belongs to the next listing: %v, %v", found, err)
				}
				if lines[0] != "acme  needs you" || lines[2] != "  authority: screen  rule: asking.permission" {
					t.Fatal(lines)
				}
				if err := listing.Announce(time.Now()); err != nil {
					t.Fatal(err)
				}
				other = read("session-aaa.json")
				if _, known := Looking(time.Now()); known {
					t.Fatal("the next listing took a reported session")
				}
			}
			if read("session-acme.json") != before || read("session-aaa.json") != other {
				t.Fatal("publishing changed the plugin's record, or handing over reconciled another")
			}
		})
	}
}

func TestOpenCodeQuestionIsProvedSeenByItsClosingMessage(t *testing.T) {
	home := sandbox(t)
	write(t, filepath.Join(home, ".agentkit", "config.toml"), opencodeConfig)
	// the session its launch reported, whose closing message Go reads in opencode.db
	token := strings.Repeat("a", 32)
	record(t, home, "acme", map[string]any{"orchestrator": "vela", "workers": []string{"vela"}, "opencode_launch": token})
	write(t, filepath.Join(stateFile(home, "opencode-launch-"+token), "session"), "ses_A012z\n")
	drawn(t, home, "acme", "Permission required\nAllow once\nEnter confirm\n")
	for file, data := range map[string]string{
		"seat-acme.json":   `{"unasked":{"text":"Which colour?","at":1}}`,
		"notify-acme.json": `{"kind":"needs","text":"Which colour?","time":1}`,
	} {
		path := stateFile(home, file)
		write(t, path, data)
		if _, known := Looking(time.Now()); !known {
			t.Fatalf("Go left a question it can prove seen to Python: %s", file)
		}
		if after, err := os.ReadFile(path); err != nil || string(after) != data {
			t.Fatalf("listing changed the question: %s, %v", after, err)
		}
		if err := os.Remove(path); err != nil {
			t.Fatal(err)
		}
	}
}
