package menu

import (
	"slices"
	"strings"
	"testing"

	"agentkit/internal/terminal"
)

func TestConfirmationKeepsTheFrameAndOnlyItsChoices(t *testing.T) {
	view := fourSeats()
	name := view.Seats[0].Name
	view.Highlight = Highlight{Cursor: name, Hidden: true}
	highlight := Highlight{Cursor: "Keep"}
	for _, size := range [][2]int{{100, 30}, {40, 20}, {24, 16}, {20, 8}} {
		frame := Draw(view, size[0], size[1]).Confirm(view.Screen, name, "Stop "+name+"?", "The seat moves to past sessions.", "Stop", highlight)
		if len(frame.Lines) > size[1]-2 || frame.Open(terminal.Key{Name: "enter"}) != "Keep" || !slices.Contains(frame.Lines, "› ✓ Keep") {
			t.Fatalf("%v: %s", size, strings.Join(frame.Lines, "\n"))
		}
		for at, line := range frame.Lines {
			if terminal.Cells(line) > size[0] {
				t.Fatalf("%v overflowed: %q", size, line)
			}
			choice := frame.Open(terminal.Key{Name: "pointer", Mouse: terminal.Mouse{Column: 3, Row: at + 1, Released: true}})
			if choice != "" && choice != "Keep" && choice != "Stop" {
				t.Fatalf("the underlying seat opened: %q", choice)
			}
		}
		if size[0] == 100 {
			at := slices.Index(frame.Lines, "  Stop "+name+"?")
			if at < 2 || frame.Lines[at-1] != "" || !strings.Contains(frame.Lines[at-2], name) {
				t.Fatalf("card is not under its row: %v", frame.Lines)
			}
		}
		for _, key := range []string{"down", "right"} {
			moved := highlight
			moved.Move(terminal.Key{Name: key}, frame)
			if moved.Cursor != "Stop" {
				t.Fatalf("%s: %+v", key, moved)
			}
		}
	}
}
