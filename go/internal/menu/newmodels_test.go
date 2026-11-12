package menu

import (
	"strings"
	"testing"

	"agentkit/internal/config"
	"agentkit/internal/terminal"
)

func TestFoldedPickerKeepsTheFocusedModelAndRoleInView(t *testing.T) {
	t.Setenv("HOME", t.TempDir())
	t.Setenv("COLUMNS", "30")
	t.Setenv("LC_ALL", "C.UTF-8")
	t.Setenv("NO_COLOR", "1")
	names := []string{"amber", "bolt", "cobalt"}
	d := &Draft{Orchestrator: "amber", Workers: names, Reviewers: names, Names: names, At: 1,
		Models: map[string]config.Model{}, Levels: map[string][]string{}}
	for _, name := range names { // drawn alike, so only the label tells the cursor's model apart
		d.Models[name] = config.Model{Harness: "acme", ID: name, Efforts: map[string]string{"effort": "low"}}
		d.Levels[name] = []string{"low", "high"}
	}
	for _, rows := range []string{"9", "10"} {
		t.Setenv("LINES", rows)
		for column, head := range []string{"orch", "builds", "reviews"} {
			d.Column = column
			shown := strings.Join(d.PickerLines((&terminal.Keyboard{}).Screen(), "14:02"), "\n")
			if !strings.Contains(shown, "› Bolt") || !strings.Contains(shown, "    "+terminal.Pad(head, 7)+"[") {
				t.Errorf("30x%s, %s focused:\n%s", rows, head, shown)
			}
		}
	}
}
