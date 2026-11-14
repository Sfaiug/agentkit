//go:build unix

package seat

import (
	"path/filepath"
	"testing"

	"agentkit/internal/config"
	"agentkit/internal/harness"
	"agentkit/internal/run"
)

// A Claude seat moved onto Codex keeps the conversation it leaves last in `left`, beside the
// account and directory it was written under, and each one already there takes those where it
// has none; a move whose launch fails puts `left` back as it was, so one the record lacked is gone;
// and a /clear claimed while the owner was asked stands, the move refused.
func TestAMoveKeepsTheConversationItLeaves(t *testing.T) {
	for _, scenario := range []string{"moved", "failed", "cleared meanwhile"} {
		t.Run(scenario, func(t *testing.T) {
			home := moveHome(t)
			if scenario != "failed" {
				write(t, filepath.Join(home, "respawns"), "")
				record(t, home, "acme", map[string]any{"orchestrator": "fable", "workers": []string{"astra"},
					"left": []any{map[string]any{"harness": "claude", "conversation": "conv-cleared"}}})
			}
			_, fields, _ := config.ResolveSession("acme")
			transcript, _ := harness.Conversation("claude", fields)
			write(t, transcript, "{\"type\":\"user\",\"message\":{\"role\":\"user\",\"content\":\"keep working\"}}\n")
			claimed := []any{run.Fields("harness", "claude", "conversation", "conv-acme")}
			known, err := Move("acme", "astra", "", func(bool) (bool, bool) {
				if scenario == "cleared meanwhile" {
					state := filepath.Join(home, ".agentkit", "state")
					if err := update(state, "acme", set([]field{{"conversation", "conv-after"}, {"left", claimed}})); err != nil {
						t.Fatal(err)
					}
				}
				return true, true
			})
			if !known || (err == nil) != (scenario == "moved") {
				t.Fatal(known, err)
			}
			after, _ := run.ReadJSON(stateFile(home, "session-acme.json"))
			cwd := run.Line(filepath.Join(home, "work", "acme"))
			want := map[string]string{
				"moved": `[{"account": null, "cwd": ` + cwd + `, "conversation": "conv-cleared", "harness": "claude"}, ` +
					`{"harness": "claude", "conversation": "conv-acme", "account": null, "cwd": ` + cwd +
					`, "transcript": ` + run.Line(transcript) + `}]`,
				"failed":            "null",
				"cleared meanwhile": run.Line(claimed),
			}[scenario]
			orchestrator := map[bool]string{true: "astra", false: "fable"}[scenario == "moved"]
			if got := run.Line(after.Get("left")); after.Str("orchestrator") != orchestrator || got != want {
				t.Fatalf("left differs on %s:\n got %s\nwant %s", after.Str("orchestrator"), got, want)
			}
		})
	}
}
