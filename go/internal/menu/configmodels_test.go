package menu

import (
	"strconv"
	"strings"
	"testing"

	"agentkit/internal/terminal"
)

func TestConfigModelsFoldPageAndPointAtTheirRows(t *testing.T) {
	t.Setenv("HOME", t.TempDir())
	rows := []ModelRow{{Name: "Acme Harness", Value: "Model One, Model Two"}}
	for i := range 30 {
		rows = append(rows, ModelRow{Name: "Model " + strconv.Itoa(i), Choice: true, Marked: i%2 == 0})
	}
	for _, width := range []int{18, 24, 35, 42, 60, 100, 120} {
		s := screenAt(t, strconv.Itoa(width))
		frame := ConfigModelsFrame(s, rows, 28, 0, "12:34", "?", "")
		if !strings.Contains(strings.Join(frame.Lines, "\n"), "Model 27") {
			t.Fatalf("selected model fell off the page at %d: %q", width, frame.Lines)
		}
		for _, line := range frame.Lines {
			if terminal.Cells(line) > width || strings.HasSuffix(line, " ") {
				t.Fatalf("bad row at %d: %q", width, line)
			}
		}
		for i, spot := range frame.spots {
			if spot.row >= 0 {
				row, _, ok := frame.Hit(terminal.Mouse{Row: i + 1, Column: 1})
				if !ok || row != spot.row {
					t.Fatalf("pointer selected %d, %v; want %d", row, ok, spot.row)
				}
			}
		}
	}
}
