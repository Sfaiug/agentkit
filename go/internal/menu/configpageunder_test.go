package menu

import (
	"strings"
	"testing"

	"agentkit/internal/terminal"
)

// limitsScreen is a `columns`×`lines` screen with no colour, and a page of three rows that step,
// each with lines of its own after the rows while the highlight is on it, as `Limits`' are.
func limitsScreen(t *testing.T, columns, lines string) (terminal.Screen, Page) {
	t.Setenv("HOME", t.TempDir())
	t.Setenv("NO_COLOR", "1")
	t.Setenv("LC_ALL", "C.UTF-8")
	t.Setenv("COLUMNS", columns)
	t.Setenv("LINES", lines)
	var rows []PageRow
	for _, label := range []string{"Review rounds", "Max lines per executor task", "Max lines per orchestrator task"} {
		rows = append(rows, PageRow{Label: label, Value: "300", Aside: "default 100",
			Step:  func(int) func() string { return func() string { return "" } },
			Under: func(terminal.Screen) []string { return strings.Split(strings.Repeat("\n  a line of "+label, 12), "\n") }})
	}
	return (&terminal.Keyboard{}).Screen(), Page{Name: "limits", Rows: rows, Move: []string{"limit", "value"}}
}

// A swipe down stops on the last row, never on one whose lines come after the rows.
func TestASwipePastRowsWithLinesOfTheirOwnStopsOnTheLast(t *testing.T) {
	s, view := limitsScreen(t, "100", "40")
	for _, view.At = range []int{0, 1} {
		for _, notches := range []int{3, 300} {
			if row, _, _ := ConfigPage(s, view).Step(notches); row != 2 {
				t.Errorf("%d notches down from row %d stop on row %d, want 2", notches, view.At, row)
			}
		}
	}
}

// ↓ through a row's lines on a short terminal and on to the next row starts that row's pages from
// its label, laid out as it is lit, however far the row before was paged.
func TestTheHighlightComingToARowStartsItsPagesFromIt(t *testing.T) {
	s, view := limitsScreen(t, "40", "13")
	view.At = 1
	frame := ConfigPage(s, view)
	for range 30 {
		pointed := view.At
		view.At, view.Choice, view.Top = frame.Step(1)
		view.Arrived = view.At != pointed
		if frame = ConfigPage(s, view); view.At != 1 {
			break
		}
	}
	if shown := strings.Join(frame.Lines, "\n"); view.At != 2 || !strings.Contains(shown, "› Max lines per orchestrator task") {
		t.Errorf("on row %d from line %d:\n%s", view.At, frame.Top, shown)
	}
}
