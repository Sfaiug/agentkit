//go:build unix

package seat

import (
	"testing"

	"agentkit/internal/run"
)

func TestMoveInPlaceOwesItsLinesAheadAtTheEffortAsksNothing(t *testing.T) {
	for model, want := range map[string]string{
		"opus":  `[{"line": "/model claude-opus", "switch": true, "pane": "%1"}, {"line": "/effort low", "switch": true, "pane": "%1"}, {"line": "hello"}]`,
		"fable": `[{"line": "/effort low", "switch": true, "pane": "%1"}, {"line": "hello"}]`, // its own model: the effort alone
	} {
		t.Run(model, func(t *testing.T) {
			home := moveHome(t)
			write(t, stateFile(home, "seat-acme.json"), `{"owed_lines":[{"line":"hello","id":"x"}],"usage_wait":{"at":1}}`)
			known, err := Move("acme", model, "low", func(bool) (bool, bool) { t.Fatal("a move in place asked"); return false, false })
			if !known || err != nil {
				t.Fatal(known, err)
			}
			after, _ := run.ReadJSON(stateFile(home, "session-acme.json"))
			if after.Str("orchestrator") != model || after.Dict("efforts").Dict(model).Str("effort") != "low" {
				t.Fatal("the record did not take the move", run.Line(after))
			}
			// the fake tmux names no pane to type into: every line stays owed
			file := revivalFile("acme")
			lines := file.List("owed_lines")
			for _, line := range lines {
				line.(*run.Object).Delete("id")
			}
			if run.Line(lines) != want || file.Get("usage_wait") != nil {
				t.Fatal("owed differs", run.Line(file))
			}
		})
	}
}
