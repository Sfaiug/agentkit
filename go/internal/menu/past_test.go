package menu

import (
	"slices"
	"strconv"
	"strings"
	"testing"
	"time"

	"agentkit/internal/terminal"
)

func TestPastKeepsItsFrameAroundLongDetailsAndPages(t *testing.T) {
	now := time.Date(2026, 11, 4, 14, 2, 0, 0, time.UTC)
	var past []PastSeat
	for i := range 12 {
		past = append(past, PastSeat{Seat: Seat{Name: "seat-" + strconv.Itoa(i+1), Checkout: "/code/acme",
			Done: 1, Total: 5, Said: strings.Repeat("Finished the changes and checked every case ", 100)}, Closed: float64(now.Unix())})
	}
	for _, size := range [][2]int{{100, 30}, {80, 10}, {40, 16}, {24, 16}, {150, 12}} {
		s := screenAt(t, strconv.Itoa(size[0]))
		h := Highlight{}
		draw := func() Frame { return DrawPast(s, past, h, now, size[0], size[1]) }
		for i := range len(past) {
			f := draw()
			if len(f.Lines) == 0 || len(f.Lines) > size[1]-2 || !strings.HasPrefix(f.Lines[0], "agentkit") || !strings.HasSuffix(f.Lines[0], "14:02") ||
				!strings.HasSuffix(f.Lines[len(f.Lines)-1], "esc back") {
				t.Fatalf("%v: lost the frame:\n%s", size, strings.Join(f.Lines, "\n"))
			}
			if f.Open(terminal.Key{Name: "enter"}) != past[i].Name {
				t.Fatalf("%v: wrong seat: %+v", size, f)
			}
			for at, line := range f.Lines {
				if terminal.Cells(line) > min(size[0], 120) || strings.HasSuffix(line, " ") {
					t.Fatalf("%v: overflowing row: %q", size, line)
				}
				first, _ := terminal.Drawn(line, 1, size[0])
				if at < len(f.spots) && f.spots[at] != "" && f.Open(terminal.Key{Name: "pointer", Mouse: terminal.Mouse{Row: at + 1, Column: first, Released: true}}) != f.spots[at] {
					t.Fatal("a past row's pointer opens another seat")
				}
			}
			h.Move(terminal.Key{Name: "down"}, f)
		}
		h = Highlight{}
		f := draw()
		h.Move(terminal.Key{Name: "right"}, f)
		if len(f.turns) > 1 && h.Cursor != f.turns[1] {
			t.Fatal("right did not turn the page")
		}
		h.Move(terminal.Key{Name: "left"}, draw())
		if h.Cursor != past[0].Name {
			t.Fatal("left did not return to the first page")
		}
	}
}

func TestPastRemovalUsesTheMenusConfirmation(t *testing.T) {
	s := screenAt(t, "80")
	now := time.Now()
	past := []PastSeat{{Seat: Seat{Name: "beta", Said: strings.Repeat("the finished work ", 100)}, Closed: float64(now.Unix())}}
	f := DrawPast(s, past, Highlight{Cursor: "beta", Hidden: true}, now, 80, 18).
		Confirm(s, "beta", "Remove beta from past sessions?", "It can no longer be reopened.", "Remove", Highlight{})
	if len(f.Lines) > 16 || !strings.HasPrefix(f.Lines[0], "agentkit · past sessions") || f.Open(terminal.Key{Name: "enter"}) != "Keep" {
		t.Fatalf("lost frame or defaulted to removal: %v", f.Lines)
	}
	h := Highlight{}
	h.Move(terminal.Key{Name: "down"}, f)
	if h.Cursor != "Remove" || !slices.Contains(f.order, "Remove") {
		t.Fatal("the confirmation cannot choose Remove")
	}
}

func TestPastDatesUseCalendarDays(t *testing.T) {
	now := time.Date(2026, 11, 4, 0, 15, 0, 0, time.UTC)
	if day, _ := pastWhen(float64(now.Add(-30*time.Minute).Unix()), now); day != "yesterday" {
		t.Fatal(day)
	}
	for _, test := range []struct {
		days int
		day  string
	}{{0, "today"}, {1, "yesterday"}, {2, "this week"}, {6, "this week"}, {7, "earlier"}} {
		if day, _ := pastWhen(float64(now.AddDate(0, 0, -test.days).Unix()), now); day != test.day {
			t.Fatalf("%d days ago: %s", test.days, day)
		}
	}
}
