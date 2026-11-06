package seat

import (
	"maps"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

func TestAntigravityStoreIsReadAtTheListingBoundary(t *testing.T) {
	for name, learned := range map[string]bool{"launcher": false, "learned": true} {
		t.Run(name, func(t *testing.T) {
			home := sandbox(t)
			write(t, filepath.Join(home, ".agentkit", "config.toml"), testConfig+gemini)
			token := strings.Repeat("a", 32)
			fields := map[string]any{"orchestrator": "gemini", "workers": []string{"gemini"},
				"antigravity_launch": token, "antigravity_open": nil}
			if learned {
				fields["conversation"], fields["id_source"] = nil, nil
				fields["antigravity_open"] = map[string]any{"launch": token, "conversation": "conv-acme"}
			}
			record(t, home, "acme", fields)
			write(t, stateFile(home, "antigravity-claim.lock"), "")
			if learned {
				// Without tmux or a store, the learned conversation must not disappear.
				record(t, home, "aaa", map[string]any{"id_source": nil})
				before := stateFiles(t, home)
				if _, known := Looking(time.Now()); known {
					t.Fatal("a learned conversation must stay with Python after tmux loses it")
				}
				if after := stateFiles(t, home); !maps.Equal(before, after) {
					t.Fatal("handing over changed the home")
				}
				return
			}
			drawn(t, home, "acme", "────────\n>\n────────\n? for shortcuts\n")
			listing, known := Looking(time.Now())
			if !known {
				t.Fatal("Go did not read the seat without a store")
			}
			before := stateFiles(t, home)["session-acme.json"]
			write(t, filepath.Join(home, ".gemini", "antigravity-cli", "conversations", "conv-acme.db"), "Python reads SQLite")
			lines, found, err := listing.Explain("acme", time.Now())
			if err != nil || !found || lines[0] != "acme  idle" || lines[2] != "  authority: screen  rule: prompt.composer" {
				t.Fatalf("the store belongs to the next listing: %v, %v, %v", lines, found, err)
			}
			if err := listing.Announce(time.Now()); err != nil {
				t.Fatal(err)
			}
			if after := stateFiles(t, home)["session-acme.json"]; after != before {
				t.Fatal("publishing changed the record Python reconciles")
			}
			// An earlier record has reconciliation to write: handing over must precede it.
			record(t, home, "aaa", map[string]any{"id_source": nil})
			files := stateFiles(t, home)
			if _, known := Looking(time.Now()); known {
				t.Fatal("the next listing took a store Python reads")
			}
			if after := stateFiles(t, home); !maps.Equal(files, after) {
				t.Fatal("handing over changed the home")
			}
		})
	}
}
