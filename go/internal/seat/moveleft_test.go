//go:build unix

package seat

import (
	"os"
	"path/filepath"
	"testing"

	"agentkit/internal/config"
	"agentkit/internal/harness"
	"agentkit/internal/run"
)

// A Claude seat moved onto Codex keeps the conversation it leaves last in `left`, beside the
// account and directory it was written under, and each one already there takes those where it
// has none; a move whose launch fails puts `left` back as it was, so one the record lacked is gone.
func TestAMoveKeepsTheConversationItLeaves(t *testing.T) {
	for _, start := range []bool{true, false} {
		t.Run(map[bool]string{true: "moved", false: "failed"}[start], func(t *testing.T) {
			home := moveHome(t)
			if start {
				write(t, filepath.Join(home, "respawns"), "")
				record(t, home, "acme", map[string]any{"orchestrator": "fable", "workers": []string{"astra"},
					"left": []any{map[string]any{"harness": "claude", "conversation": "conv-cleared"}}})
			}
			before, _ := os.ReadFile(stateFile(home, "session-acme.json"))
			_, fields, _ := config.ResolveSession("acme")
			transcript, _ := harness.Conversation("claude", fields)
			write(t, transcript, "{\"type\":\"user\",\"message\":{\"role\":\"user\",\"content\":\"keep working\"}}\n")
			known, err := Move("acme", "astra", "", func(bool) (bool, bool) { return true, true })
			if !known || (err == nil) != start {
				t.Fatal(known, err)
			}
			after, _ := run.ReadJSON(stateFile(home, "session-acme.json"))
			if !start {
				if after.Has("left") || after.Str("orchestrator") != "fable" {
					t.Fatal("a failed launch left its write", string(before), run.Line(after))
				}
				return
			}
			cwd := run.Line(filepath.Join(home, "work", "acme"))
			want := `[{"account": null, "cwd": ` + cwd + `, "conversation": "conv-cleared", "harness": "claude"}, ` +
				`{"harness": "claude", "conversation": "conv-acme", "account": null, "cwd": ` + cwd +
				`, "transcript": ` + run.Line(transcript) + `}]`
			if got := run.Line(after.Get("left")); after.Str("orchestrator") != "astra" || got != want {
				t.Fatalf("left differs:\n got %s\nwant %s", got, want)
			}
		})
	}
}
