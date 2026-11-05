package seat

import (
	"maps"
	"path/filepath"
	"testing"
	"time"
)

const grokConfig = testConfig + "[models.nova]\nharness='grokbuild'\nmodel='grok-test'\neffort='high'\nprovider='test'\n"
const grokTrust = "Do you trust the contents of this directory?\nYes, proceed\nNo, quit\n"

func TestGrokBuildScreenLeavesReconciliationToPython(t *testing.T) {
	for _, each := range []struct {
		name                 string
		conversation, source any
		ready                bool
	}{
		{"launcher issued", "conv-acme", "launcher", true},
		{"not issued", "legacy", nil, false},
		{"another source", "legacy", "other", false},
		{"no conversation", nil, nil, true},
	} {
		t.Run(each.name, func(t *testing.T) {
			home := sandbox(t)
			write(t, filepath.Join(home, ".agentkit", "config.toml"), grokConfig)
			// An earlier record needs reconciliation too: refusal must precede every write.
			record(t, home, "aaa", map[string]any{"id_source": nil, "repo": nil})
			record(t, home, "acme", map[string]any{"orchestrator": "nova", "workers": []string{"nova"},
				"conversation": each.conversation, "id_source": each.source})
			drawn(t, home, "acme", grokTrust)
			before := stateFiles(t, home)
			listing, known := Looking(time.Now())
			if known != each.ready {
				t.Fatalf("readiness=%v, want %v", known, each.ready)
			}
			if !known {
				if !maps.Equal(before, stateFiles(t, home)) {
					t.Fatal("handing over changed state")
				}
				return
			}
			lines, found, err := listing.Explain("acme", time.Now())
			if err != nil || !found || lines[0] != "acme  needs you" || lines[2] != "  authority: screen  rule: asking.trust" {
				t.Fatalf("%v, found=%v, err=%v", lines, found, err)
			}
			if err := listing.Announce(time.Now()); err != nil {
				t.Fatal(err)
			}
			if stateFiles(t, home)["session-acme.json"] != before["session-acme.json"] {
				t.Fatal("publishing the word reconciled the record")
			}
			// A stale listing cannot clear or rewrite a newer, unissued conversation.
			record(t, home, "acme", map[string]any{"orchestrator": "nova", "workers": []string{"nova"}, "id_source": nil})
			before = stateFiles(t, home)
			if err := listing.Announce(time.Now()); err != nil {
				t.Fatal(err)
			}
			if stateFiles(t, home)["session-acme.json"] != before["session-acme.json"] {
				t.Fatal("publishing changed the newer record")
			}
			if _, known := Looking(time.Now()); known {
				t.Fatal("the next listing took a record owed reconciliation")
			}
		})
	}
}

func TestGrokBuildHookFactsBelongToTheNextListingAndPython(t *testing.T) {
	for name, late := range map[string]bool{"already reported": false, "reported while publishing": true} {
		t.Run(name, func(t *testing.T) {
			home := sandbox(t)
			write(t, filepath.Join(home, ".agentkit", "config.toml"), grokConfig)
			record(t, home, "aaa", map[string]any{"id_source": nil})
			record(t, home, "acme", map[string]any{"orchestrator": "nova", "workers": []string{"nova"}})
			drawn(t, home, "acme", grokTrust)
			listing, known := Looking(time.Now())
			if !known {
				t.Fatal("Go did not read the screen before any hook")
			}
			write(t, stateFile(home, "hook-acme.json"), `{"session":"acme","event":"Notification","kind":"permission_prompt","at":1}`)
			before := stateFiles(t, home)
			if late {
				lines, found, err := listing.Explain("acme", time.Now())
				if err != nil || !found || lines[0] != "acme  needs you" || lines[2] != "  authority: screen  rule: asking.trust" {
					t.Fatalf("the hook belongs to the next listing: %v, %v, %v", lines, found, err)
				}
				if err := listing.Announce(time.Now()); err != nil {
					t.Fatal(err)
				}
				if stateFiles(t, home)["session-acme.json"] != before["session-acme.json"] {
					t.Fatal("publishing reconciled the record")
				}
				before = stateFiles(t, home)
			}
			if _, known := Looking(time.Now()); known {
				t.Fatal("Go took a Grok Build hook fact")
			}
			if !maps.Equal(before, stateFiles(t, home)) {
				t.Fatal("handing the hook to Python changed state")
			}
		})
	}
}
