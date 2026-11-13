package menu

import (
	"slices"
	"strings"
	"testing"

	"agentkit/internal/terminal"
)

func TestAnOpenLongTextKeepsTheFrameAndItsPointerPlaces(t *testing.T) {
	view := fourSeats()
	view.Seats[0].Unsent = strings.Repeat("What should happen next? ", 80)
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
	seat := Seat{Word: "working", Model: "Opus", Builds: []string{"Spark", "Fable"}, Reviews: []string{"Fable"},
		Tasks: []Task{{Stage: 0, Moving: true}, {Stage: 0}, {Stage: 1, Moving: true}, {Stage: 2}}}
	for room, want := range map[int]string{
		80: "Opus orchestrates   Spark builds   Fable builds, reviews   ■□□  ■□□  ■■□  ■■■",
		61: "Opus orchestrates   Spark builds   Fable builds, reviews   +4",
		40: "Opus orchestrates   Spark builds…   +4",
		5:  "   +4",
	} {
		if got := detail(terminal.Screen{}, seat, room, nil); len(got) != 1 || got[0] != want || terminal.Cells(got[0]) > room {
			t.Errorf("room %d: %q, want %q", room, got, want)
		}
	}
}

func TestEnterOnAHiddenHighlightOnlyBringsItBack(t *testing.T) {
	view := fourSeats()
	name := view.Seats[1].Name
	view.Highlight = Highlight{Cursor: name, Hidden: true}
	enter := terminal.Key{Name: "enter"}
	drawn := Draw(view, 100, 30)
	if opened := drawn.Open(enter); opened != "" {
		t.Fatalf("Enter opened %q", opened)
	}
	if !view.Highlight.Move(enter, drawn) || view.Highlight != (Highlight{Cursor: name}) {
		t.Fatalf("%+v", view.Highlight)
	}
	if opened := Draw(view, 100, 30).Open(enter); opened != name {
		t.Fatalf("the second Enter opened %q", opened)
	}
}

// Whatever a seat's word, its row opens who builds and reviews, never a sentence the seat or ak
// says of it (menu.detail; no Seat holds one): the keyboard's under the highlighted row alone, a
// pipe's, drawn as it is, under every row.
func TestEveryWordOpensItsCrewAndNoSentence(t *testing.T) {
	view := View{Clock: "14:02", Keys: Keys(terminal.Screen{}, false)}
	models := []string{"Fable 5.1 xhigh"}
	// a seat tmux lost, one asking the owner, one done and one out of usage
	for i, each := range []Seat{{Name: "atoll-lost", Word: "idle"}, {Name: "atoll-ask", Word: "needs you"},
		{Name: "atoll-done", Word: "done", Done: 2, Total: 2}, {Name: "atoll-spent", Word: "out of usage"}} {
		each.Number, each.Checkout, each.Model, each.Builds, each.Reviews = i+1, "/home/acme/code/atoll", models[0], models, models
		view.Seats = append(view.Seats, each)
	}
	// each row's name to the lines under it, up to the next row or blank
	under := func(height int) map[string][]string {
		opened, name := map[string][]string{}, ""
		for _, line := range Lines(view, 100, height) {
			switch fields := strings.Fields(strings.TrimPrefix(line, "›")); {
			case line == "":
				name = ""
			case len(fields) > 1 && strings.HasPrefix(fields[1], "atoll-"):
				name, opened[fields[1]] = fields[1], nil
			case name != "":
				opened[name] = append(opened[name], line)
			}
		}
		return opened
	}
	crew := []string{"     Fable 5.1 xhigh ⚒◎"}
	for _, lit := range view.Seats {
		view.Highlight = Highlight{Cursor: lit.Name, Open: true}
		opened := under(30)
		for _, each := range view.Seats {
			if want := map[bool][]string{true: crew}[each.Name == lit.Name]; !slices.Equal(opened[each.Name], want) {
				t.Errorf("%s lit, under %s: %q, want %q", lit.Name, each.Name, opened[each.Name], want)
			}
		}
	}
	view.Highlight, view.Pipe = Highlight{}, true
	opened := under(0)
	for _, each := range view.Seats {
		if !slices.Equal(opened[each.Name], crew) {
			t.Errorf("piped, under %s: %q", each.Name, opened[each.Name])
		}
	}
}
