package menu

import (
	"strconv"
	"strings"
	"testing"

	"agentkit/internal/config"
	"agentkit/internal/matrix"
	"agentkit/internal/run"
	"agentkit/internal/terminal"
)

func TestConfigRolesFoldAndThePageKeepsItsSelectedCell(t *testing.T) {
	t.Setenv("HOME", t.TempDir())
	selected := run.NewObject()
	selected.Set("orchestrator", "amber")
	selected.Set("workers", []any{"bolt"})
	c := &matrix.Configuration{Names: []string{"amber", "bolt"}, Models: map[string]config.Model{
		"amber": {Harness: "acme", ID: "Amber 1.0", Efforts: map[string]string{"effort": "high"}},
		"bolt":  {Harness: "acme", ID: "Bolt 2.0", Efforts: map[string]string{"effort": "medium"}},
	}, Levels: map[string][]string{"amber": {"low", "medium", "high"}, "bolt": {"low", "medium", "high"}}, Selected: selected}
	for _, width := range []int{18, 24, 35, 42, 60, 100, 120} {
		s := screenAt(t, strconv.Itoa(width))
		view := ConfigView{Matrix: c, Row: 1, Column: 2, Scope: "acme", Version: "?", Clock: "12:34"}
		body := configBody(s, view)
		for _, row := range body {
			if terminal.Cells(row.line) > width {
				t.Errorf("at %d columns, row has %d: %q", width, terminal.Cells(row.line), row.line)
			}
		}
		frame := ConfigFrame(s, view)
		if !strings.Contains(strings.Join(frame.Lines, "\n"), "[■]") {
			t.Errorf("at %d columns the selected cell is off its page: %q", width, frame.Lines)
		}
		for number, spot := range frame.spots {
			for _, cell := range spot.cells {
				first, _ := terminal.Drawn(frame.Lines[number], cell.first, cell.last)
				row, column, ok := frame.Hit(terminal.Mouse{Row: number + 1, Column: first})
				if !ok || row != spot.row || column != cell.column {
					t.Fatalf("at %d columns, cell points to (%d, %d, %v)", width, row, column, ok)
				}
			}
		}
	}
}
