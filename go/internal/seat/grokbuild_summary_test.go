package seat

import (
	"maps"
	"path/filepath"
	"testing"
	"time"
)

func TestGrokBuildSummaryLeavesChangedSettingsToPython(t *testing.T) {
	for _, folder := range []string{".grok", "custom-grok"} {
		for _, each := range []struct {
			name, summary, effort string
			ready                 bool
		}{
			{"missing", "", "", true},
			{"unreadable", "{", "", true},
			{"not an object", "[]", "", true},
			{"no model", `{"reasoning_effort":"low"}`, "", true},
			{"empty model", `{"current_model_id":"","reasoning_effort":"low"}`, "", true},
			{"same settings", `{"current_model_id":"grok-test","reasoning_effort":"high"}`, "", true},
			{"model changed", `{"current_model_id":"grok-other","reasoning_effort":"high"}`, "", false},
			{"effort changed", `{"current_model_id":"grok-test","reasoning_effort":"low"}`, "", false},
			{"saved effort matches", `{"current_model_id":"grok-test","reasoning_effort":"low"}`, "low", true},
			{"saved effort differs", `{"current_model_id":"grok-test","reasoning_effort":"high"}`, "low", false},
			{"no effort", `{"current_model_id":"grok-test"}`, "", true},
		} {
			t.Run(each.name+"/"+folder, func(t *testing.T) {
				home := sandbox(t)
				write(t, filepath.Join(home, ".agentkit", "config.toml"), grokConfig)
				root := filepath.Join(home, folder)
				t.Setenv("GROK_HOME", "")
				if folder != ".grok" {
					t.Setenv("GROK_HOME", root)
					write(t, filepath.Join(home, ".grok", "sessions", "%2Fwork%2Facme%20%2B%3A%40%2Fcaf%C3%A9", "conv-acme", "summary.json"),
						`{"current_model_id":"grok-other"}`)
				}
				// The earlier seat would be reconciled if refusal came after publication.
				record(t, home, "aaa", map[string]any{"id_source": nil})
				fields := map[string]any{"orchestrator": "nova", "workers": []string{"nova"}, "cwd": "/work/acme +:@/café"}
				if each.effort != "" {
					fields["efforts"] = map[string]any{"nova": map[string]string{
						"effort": each.effort, "exec_effort": "medium", "review_effort": "xhigh"}}
				}
				record(t, home, "acme", fields)
				if each.summary != "" {
					write(t, filepath.Join(root, "sessions", "%2Fwork%2Facme%20%2B%3A%40%2Fcaf%C3%A9", "conv-acme", "summary.json"), each.summary)
				}
				drawn(t, home, "acme", grokTrust)
				before := stateFiles(t, home)
				listing, known := Looking(time.Now())
				if known != each.ready || !maps.Equal(before, stateFiles(t, home)) {
					t.Fatalf("readiness=%v, want %v, or reading changed state", known, each.ready)
				}
				if known {
					if err := listing.Announce(time.Now()); err != nil {
						t.Fatal(err)
					}
					if stateFiles(t, home)["session-acme.json"] != before["session-acme.json"] {
						t.Fatal("publishing reconciled the record")
					}
				}
			})
		}
	}
}

func TestGrokBuildSummaryChangesBelongToTheNextListing(t *testing.T) {
	home := sandbox(t)
	t.Setenv("GROK_HOME", "")
	write(t, filepath.Join(home, ".agentkit", "config.toml"), grokConfig)
	record(t, home, "acme", map[string]any{"orchestrator": "nova", "workers": []string{"nova"}, "cwd": "/work/acme"})
	drawn(t, home, "acme", grokTrust)
	listing, known := Looking(time.Now())
	if !known {
		t.Fatal("the seat without a summary needs no reconciliation")
	}
	write(t, filepath.Join(home, ".grok", "sessions", "%2Fwork%2Facme", "conv-acme", "summary.json"),
		`{"current_model_id":"grok-other","reasoning_effort":"low"}`)
	before := stateFiles(t, home)
	lines, found, err := listing.Explain("acme", time.Now())
	if err != nil || !found || lines[0] != "acme  needs you" || lines[2] != "  authority: screen  rule: asking.trust" {
		t.Fatalf("the summary belongs to the next listing: %v, %v, %v", lines, found, err)
	}
	if stateFiles(t, home)["session-acme.json"] != before["session-acme.json"] {
		t.Fatal("publishing reconciled the record")
	}
	before = stateFiles(t, home)
	if _, known := Looking(time.Now()); known || !maps.Equal(before, stateFiles(t, home)) {
		t.Fatal("the next listing must hand the changed summary to Python without writing")
	}
}
