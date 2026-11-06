package menu

import (
	"testing"

	"agentkit/internal/terminal"
)

// A swipe past a page's last or first row stops on it.
func TestAStepPastAPagesEndStopsOnItsLastRow(t *testing.T) {
	view := Page{Name: "machines", Rows: []PageRow{{Label: "acme"}, {Label: "bolt"}, {Label: "crux"}}}
	for step, want := range map[int]int{300: 2, -300: 0, 1: 2} {
		view.At = 1
		if at, _ := ConfigPage(terminal.Screen{}, view).Step(step); at != want {
			t.Errorf("%d rows on from bolt is row %d, want %d", step, at, want)
		}
	}
}
