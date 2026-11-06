//go:build unix

package seat

import (
	"path/filepath"
	"testing"

	"agentkit/internal/run"
)

func TestMoveRetiresQueuedSwitchesOnlyAfterRestart(t *testing.T) {
	for _, queue := range []struct {
		name, before, after, reset string
	}{
		{"mixed", `[{"line":"/model claude-fable","switch":true,"pane":"%1","id":"old"},{"line":"continue the endpoint","id":"keep","typed":{"pane":"%1"}},{"line":"/effort high","switch":true,"pane":"%1","typed":{"pane":"%1"}}]`, `[{"line":"continue the endpoint","id":"keep"}]`, `[{"line":"/model claude-fable","switch":true,"pane":"%1","id":"old"},{"line":"continue the endpoint","id":"keep"},{"line":"/effort high","switch":true,"pane":"%1"}]`},
		{"switches", `[{"line":"/model claude-fable","switch":true,"pane":"%1"}]`, `null`, ""},
		{"ordinary", `[{"line":"continue the endpoint","id":"keep"}]`, `[{"line":"continue the endpoint","id":"keep"}]`, ""},
	} {
		for _, start := range []bool{false, true} {
			name := "refused"
			if start {
				name = "started"
			}
			t.Run(queue.name+"/"+name, func(t *testing.T) {
				home := moveHome(t)
				if start {
					write(t, filepath.Join(home, "respawns"), "")
				}
				write(t, stateFile(home, "seat-acme.json"), `{"owed_lines":`+queue.before+`}`)
				known, err := Move("acme", "astra", func() (bool, bool) { return true, true })
				if !known || (err == nil) != start {
					t.Fatal("move result", known, err)
				}
				want := queue.before
				// Receipts are reset before respawn; a refused attempt still owes
				// every instruction and id, including the old switch commands.
				if queue.reset != "" {
					want = queue.reset
				}
				if start {
					want = queue.after
				}
				expected, err := run.Decode([]byte(want))
				if err != nil {
					t.Fatal(err)
				}
				if got := revivalFile("acme").Get("owed_lines"); !run.Equal(got, expected) {
					t.Fatalf("queued lines after %s: %s; want %s", name, run.Line(got), want)
				}
			})
		}
	}
}
