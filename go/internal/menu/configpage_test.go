package menu

import (
	"slices"
	"strconv"
	"strings"
	"testing"

	"agentkit/internal/terminal"
)

// A swipe past a page's last or first row stops on it, and past an open list's last or first
// choice on that.
func TestAStepPastAPagesEndStopsOnItsLastRow(t *testing.T) {
	view := Page{Name: "machines", Rows: []PageRow{{Label: "acme"}, {Label: "bolt"}, {Label: "crux"}}}
	for step, want := range map[int]int{300: 2, -300: 0, 1: 2} {
		view.At = 1
		if at, _, _ := ConfigPage(terminal.Screen{}, view).Step(step); at != want {
			t.Errorf("%d rows on from bolt is row %d, want %d", step, at, want)
		}
	}
	t.Setenv("HOME", t.TempDir())
	s := screenAt(t, "60")
	view.Choices = []PageRow{{Value: "one"}, {Value: "two"}, {Value: "three"}}
	for step, want := range map[int]int{300: 2, -300: 0, 1: 2} {
		view.Choice = 1
		if at, choice, _ := ConfigPage(s, view).Step(step); at != 1 || choice != want {
			t.Errorf("%d choices on from two is row %d choice %d, want row 1 choice %d", step, at, choice, want)
		}
	}
}

func TestAnOpenListFoldsPagesAndPointsAtItsChoices(t *testing.T) {
	t.Setenv("HOME", t.TempDir())
	view := Page{Name: "models", Rows: []PageRow{{Label: "Acme Harness", Value: "Model One, Model Two", Several: true}, {Label: "Other", Value: "none"}},
		Choice: 27, Clock: "12:34"}
	for i := range 30 {
		view.Choices = append(view.Choices, PageRow{Value: "Model " + strconv.Itoa(i), On: i%2 == 0, Flip: func() string { return "" }})
	}
	for _, width := range []int{18, 24, 35, 42, 60, 100, 120} {
		s := screenAt(t, strconv.Itoa(width))
		frame := ConfigPage(s, view)
		if !strings.Contains(strings.Join(frame.Lines, "\n"), "Model 27") {
			t.Fatalf("selected model fell off the page at %d: %q", width, frame.Lines)
		}
		for _, line := range frame.Lines {
			if terminal.Cells(line) > width || strings.HasSuffix(line, " ") {
				t.Fatalf("bad row at %d: %q", width, line)
			}
		}
		for i, entry := range frame.lines[frame.Top:min(len(frame.lines), frame.Top+frame.page)] {
			row, choice, ok := frame.Hit(terminal.Mouse{Row: i + 3, Column: 1})
			if !ok || row != entry.row || choice != entry.choice {
				t.Fatalf("pointer selected %d %d, %v; want %v", row, choice, ok, entry)
			}
		}
		if row, choice, _ := frame.Step(1); row != 0 || choice != 28 {
			t.Fatalf("a step left the list at %d: %d %d", width, row, choice)
		}
	}
}

// A value as short as a cell beside a label that leaves it none folds under its label, never cut:
// its row takes a second line, and no line is wider than the terminal.
func TestAValueBesideALabelThatLeavesItNoRoomFolds(t *testing.T) {
	t.Setenv("HOME", t.TempDir())
	const label = "Max lines per orchestrator task"
	view := Page{Name: "limits", Rows: []PageRow{{Label: "Review rounds", Value: "3"}, {Label: label, Value: "50"}}}
	for width := 20; width <= 40; width++ {
		frame := ConfigPage(screenAt(t, strconv.Itoa(width)), view)
		folded := width < 2+len(label)+2+1 // the room the widest label leaves beside it holds no cell
		if got := slices.Index(frame.lines, pageEntry{1, -1}) == 2; got != folded {
			t.Errorf("at %d columns 3 folded: %v, want %v", width, got, folded)
		}
		for _, line := range frame.Lines {
			if terminal.Cells(line) > width {
				t.Errorf("a line is wider than %d columns: %q", width, line)
			}
		}
	}
}
