package seat

import (
	"fmt"
	"maps"
	"path/filepath"
	"testing"
	"time"

	"agentkit/internal/run"
)

const grokSummaryDir = "%2Fwork%2Facme%20%2B%3A%40%2Fcaf%C3%A9"

// grokSummarySeat is a Grok Build seat on nova, launched ten minutes ago, whose summary.json under
// root holds that summary, if any, and whose seat file holds file, if any.
func grokSummarySeat(t *testing.T, root, summary, file string) string {
	t.Helper()
	home := filepath.Dir(root)
	write(t, filepath.Join(home, ".agentkit", "config.toml"),
		grokConfig+"[models.swift]\nharness='grokbuild'\nmodel='grok-other'\neffort='high'\nprovider='test'\n")
	record(t, home, "acme", map[string]any{"orchestrator": "nova", "workers": []string{"nova"}, "cwd": "/work/acme +:@/café",
		"launched": time.Now().Unix() - 600})
	if summary != "" {
		write(t, filepath.Join(root, "sessions", grokSummaryDir, "conv-acme", "summary.json"), summary)
	}
	if file != "" {
		write(t, stateFile(home, "seat-acme.json"), file)
	}
	return home
}

// grokFollowed fails unless the record runs that orchestrator at that effort, or for "" is the
// one before.
func grokFollowed(t *testing.T, home, before, orchestrator, effort string) {
	t.Helper()
	after := stateFiles(t, home)["session-acme.json"]
	got, _ := run.ReadJSON(stateFile(home, "session-acme.json"))
	if orchestrator == "" && after != before {
		t.Fatalf("the record moved: %s", after)
	}
	efforts := got.Dict("efforts")
	if orchestrator != "" && (got.Str("orchestrator") != orchestrator || efforts == nil || efforts.Dict(orchestrator) == nil ||
		efforts.Dict(orchestrator).Str("effort") != effort) {
		t.Fatalf("want %s at %s: %s", orchestrator, effort, after)
	}
}

// Grok Build saves `/model` and effort changes in summary.json before any answer: Go keeps the
// listing whatever it holds, and its look moves the record to what it saved since the launch or
// the last move in place, while none is still owed.
func TestGrokBuildSummaryMovesTheSeatOnItsLook(t *testing.T) {
	later := fmt.Sprintf(`{"switched":%d}`, time.Now().Unix()+600)
	owed := `{"owed_lines":[{"id":"x","line":"/model grok-test","switch":true}]}`
	for _, folder := range []string{".grok", "custom-grok"} {
		for _, each := range []struct {
			name, summary, file  string
			orchestrator, effort string // "" where the record stays as it was
		}{
			{"missing", "", "", "", ""},
			{"unreadable", "{", "", "", ""},
			{"not an object", "[]", "", "", ""},
			{"no model", `{"reasoning_effort":"low"}`, "", "", ""},
			{"same settings", `{"current_model_id":"grok-test","reasoning_effort":"high"}`, "", "", ""},
			{"no model configured", `{"current_model_id":"grok-unknown","reasoning_effort":"low"}`, "", "", ""},
			{"saved before the last move", `{"current_model_id":"grok-other","reasoning_effort":"low"}`, later, "", ""},
			{"a move still owed", `{"current_model_id":"grok-other","reasoning_effort":"low"}`, owed, "", ""},
			{"model changed", `{"current_model_id":"grok-other","reasoning_effort":"high"}`, "", "swift", "high"},
			{"effort changed", `{"current_model_id":"grok-test","reasoning_effort":"low"}`, "", "nova", "low"},
			{"both changed", `{"current_model_id":"grok-other","reasoning_effort":"medium"}`, "", "swift", "medium"},
		} {
			t.Run(each.name+"/"+folder, func(t *testing.T) {
				root := filepath.Join(sandbox(t), folder)
				t.Setenv("GROK_HOME", "")
				if folder != ".grok" {
					t.Setenv("GROK_HOME", root)
					write(t, filepath.Join(filepath.Dir(root), ".grok", "sessions", grokSummaryDir, "conv-acme", "summary.json"),
						`{"current_model_id":"grok-other"}`)
				}
				home := grokSummarySeat(t, root, each.summary, each.file)
				drawn(t, home, "acme", grokTrust)
				before := stateFiles(t, home)
				listing, known := Looking(time.Now())
				if !known || !maps.Equal(before, stateFiles(t, home)) {
					t.Fatalf("known=%v, or reading changed state", known)
				}
				if err := listing.Announce(time.Now()); err != nil {
					t.Fatal(err)
				}
				grokFollowed(t, home, before["session-acme.json"], each.orchestrator, each.effort)
			})
		}
	}
}

// The tick's health look follows the summary too, before its account decision reads the model.
func TestGrokBuildHealthFollowsTheSummary(t *testing.T) {
	root := filepath.Join(sandbox(t), "custom-grok")
	t.Setenv("GROK_HOME", root)
	home := grokSummarySeat(t, root, `{"current_model_id":"grok-other","reasoning_effort":"low"}`, "")
	drawn(t, home, "acme", grokTrust)
	if carried, err := Health("acme", func(Live) bool { return true }, func(string) {}); !carried || err != nil {
		t.Fatalf("carried=%v, err=%v", carried, err)
	}
	grokFollowed(t, home, "", "swift", "low")
}

// A seat nobody is in is read before its announce lock is taken: a launch or a move in place
// since then leaves that summary moving nothing.
func TestGrokBuildFollowIsRecountedUnderTheLock(t *testing.T) {
	for _, bound := range []string{"launched", "switched"} {
		t.Run(bound, func(t *testing.T) {
			root := filepath.Join(sandbox(t), "custom-grok")
			t.Setenv("GROK_HOME", root)
			home := grokSummarySeat(t, root, `{"current_model_id":"grok-other","reasoning_effort":"low"}`, "")
			listing, known := Looking(time.Now())
			if !known {
				t.Fatal("Go did not read the seat")
			}
			now := run.Float(float64(time.Now().Unix() + 1))
			moved := Write("acme", "switched", now)
			if bound == "launched" {
				moved = Update("acme", func(record *run.Object) bool { record.Set("launched", now); return true })
			}
			if moved != nil {
				t.Fatal(moved)
			}
			before := stateFiles(t, home)["session-acme.json"]
			if err := listing.Announce(time.Now()); err != nil {
				t.Fatal(err)
			}
			grokFollowed(t, home, before, "", "")
		})
	}
}
