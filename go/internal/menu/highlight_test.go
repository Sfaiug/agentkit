package menu

import (
	"strings"
	"testing"

	"agentkit/internal/terminal"
)

func TestAnOpenQuestionKeepsTheFrameAndItsPointerPlaces(t *testing.T) {
	view := fourSeats()
	view.Seats[0].Said = strings.Repeat("What should happen next? ", 80)
	view.Highlight = Highlight{Cursor: view.Seats[0].Name, Open: true}
	for _, size := range [][2]int{{100, 30}, {40, 20}, {24, 16}, {20, 8}} {
		drawn := Draw(view, size[0], size[1])
		if len(drawn.Lines) > max(2, size[1]-2) {
			t.Fatalf("%v overflowed: %s", size, strings.Join(drawn.Lines, "\n"))
		}
		for at, name := range drawn.spots {
			if name != view.Seats[0].Name {
				continue
			}
			var highlight Highlight
			first, _ := terminal.Drawn(drawn.Lines[at], 1, size[0])
			highlight.Move(terminal.Key{Name: "pointer", Mouse: terminal.Mouse{Column: first, Row: at + 1, Button: 35}}, drawn)
			if highlight.Cursor != name || !highlight.Open || highlight.Hidden {
				t.Fatalf("%v row %d: %+v", size, at, highlight)
			}
		}
	}
}

func TestTasksGiveWayToACountWhileTheCrewKeepsItsRoles(t *testing.T) {
	seat := Seat{Word: "working", Builds: []string{"Spark", "Fable"}, Reviews: []string{"Fable"},
		Tasks: []Task{{Stage: 0, Moving: true}, {Stage: 0}, {Stage: 1, Moving: true}, {Stage: 2}}}
	for room, want := range map[int]string{
		80: "Spark ⚒   Fable ⚒◎   ■□□  ■□□  ■■□  ■■■",
		25: "Spark ⚒   Fable ⚒◎   +4",
		5:  "   +4",
	} {
		if got := detail(terminal.Screen{}, seat, room, nil); len(got) != 1 || got[0] != want || terminal.Cells(got[0]) > room {
			t.Errorf("room %d: %q, want %q", room, got, want)
		}
	}
}
