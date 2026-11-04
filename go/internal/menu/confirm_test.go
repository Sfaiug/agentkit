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
	for _, size := range [][2]int{{100, 30}, {40, 20}, {24, 30}} {
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
		first := slices.IndexFunc(frame.Lines, func(line string) bool { return strings.HasPrefix(line, "  Stop ") })
		row := slices.IndexFunc(frame.Lines, func(line string) bool { return strings.Contains(line, name) && !strings.HasPrefix(line, "  Stop ") })
		if row < 0 || first <= row || frame.Lines[first-1] != "" {
			t.Fatalf("card is not under its row: %v", frame.Lines)
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

func TestConfirmationHandsOverRatherThanCroppingItsTargetOrQuestion(t *testing.T) {
	view := View{Seats: []Seat{
		{Number: 1, Name: "acme", Model: "Opus 5.5", Word: "working"},
		{Number: 2, Name: "beta", Model: "Opus 5.5", Word: "idle"},
	}, Highlight: Highlight{Cursor: "acme", Hidden: true}}
	for _, size := range [][2]int{{40, 12}, {24, 16}, {80, 10}, {80, 8}} {
		frame := Draw(view, size[0], size[1]).Confirm(view.Screen, "acme", "Stop acme and everything it runs?",
			"No runs stop with it; the session moves to past sessions, p, where it reopens where it stopped.", "Stop", Highlight{Cursor: "Keep"})
		if len(frame.Lines) != 0 {
			t.Fatalf("%v should hand over: %s", size, strings.Join(frame.Lines, "\n"))
		}
	}
}
