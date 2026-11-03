package menu

import (
	"strings"
	"testing"

	"agentkit/internal/terminal"
)

// fourSeats is a project of two and two filed under none, under six subscriptions with no reading.
func fourSeats() View {
	view := View{Clock: "14:02", Keys: Keys(terminal.Screen{}, false)}
	for i, each := range []Seat{{Name: "atoll-ask", Checkout: "/home/acme/code/atoll", Word: "needs you"},
		{Name: "atoll-fix", Checkout: "/home/acme/code/atoll", Word: "working"},
		{Name: "beta", Word: "idle"}, {Name: "gamma-with-a-longer-name", Word: "idle", Unsent: "fix the dates"}} {
		each.Number, each.Model = i+1, "Opus 5.5"
		view.Seats = append(view.Seats, each)
	}
	for _, label := range []string{"Claude", "MiMo", "Muse", "Gemini", "Grok", "ChatGPT"} {
		view.Cells = append(view.Cells, Cell{Label: label, Left: -1, Said: "—  no reading yet"})
	}
	return view
}

func TestAShortScreenFoldsTheUsageAndTurnsPages(t *testing.T) {
	got := Lines(fourSeats(), 100, 11)
	want := []string{"  Claude — · MiMo — · Muse — · Gemini — · Grok — · ChatGPT —", "atoll",
		"› 1  atoll-ask                 Opus 5.5  ! needs you",
		"  2  atoll-fix                 Opus 5.5  ● working    ────────────────────────────────── no plan yet",
		"", "not assigned yet", "  3  beta                      Opus 5.5  ○ idle", "",
		"  ←  1 / 2  →   ↑↓←→ move   ⏎ open   n new   c config   esc leave"}
	if strings.Join(got, "\n") != strings.Join(want, "\n") {
		t.Fatalf("got\n%s", strings.Join(got, "\n"))
	}
}

func TestEverySizeHasAFrame(t *testing.T) {
	for _, size := range [][2]int{{100, 14}, {40, 20}, {40, 12}, {24, 16}, {20, 3}, {1, 1}, {200, 60}} {
		if got := Lines(fourSeats(), size[0], size[1]); len(got) == 0 {
			t.Errorf("%v: no frame", size)
		}
	}
}
