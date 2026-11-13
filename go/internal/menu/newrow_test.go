package menu

import (
	"fmt"
	"reflect"
	"strings"
	"testing"

	"agentkit/internal/config"
	"agentkit/internal/terminal"
)

func draftOf() *Draft {
	return &Draft{Hint: "rex", Orchestrator: "alpha", Workers: []string{"alpha", "beta"},
		Reviewers: []string{"alpha", "beta"}, Names: []string{"alpha", "beta"},
		Models: map[string]config.Model{"alpha": {ID: "default"}, "beta": {ID: "default"}},
		Taken:  map[string]bool{"acme": true}}
}

func TestDraftRefusesTheNameItWillActuallyOpen(t *testing.T) {
	d := draftOf()
	for _, char := range "--ACME-" {
		d.Key(terminal.Key{Name: "char", Char: string(char)})
	}
	if d.Name() != "acme" || d.Refusal() != "a seat is called acme already" {
		t.Fatalf("%q: %s", d.Name(), d.Refusal())
	}
	for range 50 {
		d.Key(terminal.Key{Name: "backspace"})
	}
	if d.Name() != "rex" || d.Refusal() != "" {
		t.Fatal("an emptied name did not return to its hint")
	}
}

func TestDraftPickerKeepsAReviewerAndIndependentGroups(t *testing.T) {
	d := draftOf()
	d.Picker = true
	for _, key := range []string{"down", "right", "space", "right", "space", "up", "space", "esc"} {
		d.Key(terminal.Key{Name: key})
	}
	if d.Picker || !reflect.DeepEqual(d.Workers, []string{"alpha"}) || !reflect.DeepEqual(d.Reviewers, []string{"alpha"}) {
		t.Fatalf("%+v", d)
	}
	d.Picker = true
	for _, char := range "beta" {
		d.Key(terminal.Key{Name: "char", Char: string(char)})
	}
	if d.Orchestrator != "beta" || d.At != 1 {
		t.Fatal("the typed model did not orchestrate")
	}
	d.Names, d.Find = []string{"alpha", "alpha-two"}, ""
	for _, char := range "alpha-two" {
		d.Key(terminal.Key{Name: "char", Char: string(char)})
	}
	if d.Orchestrator != "alpha-two" {
		t.Fatal("a name's prefix selected another model")
	}
}

func TestANewSeatsCrewIsOneLineCutToItsRoomOnAPhone(t *testing.T) {
	d := &Draft{Hint: "fix-api", Orchestrator: "opus", Workers: []string{"astra"}, Reviewers: []string{"fable"},
		Models: map[string]config.Model{"opus": {ID: "default"}, "astra": {ID: "default"}, "fable": {ID: "default"}}}
	v, s := (View{New: d}).withNew(), terminal.Screen{}
	got := d.block(s, v.Seats[0], columns(s, v.Seats, 40))
	if len(got) != 2 || strings.TrimSpace(got[1].line) != "opus orchestrates   astra builds…" {
		t.Fatalf("%+v", got)
	}
}

func TestDraftStaysVisibleAcrossPagesAndKeepsTheNameCaret(t *testing.T) {
	for _, width := range []int{100, 40, 24} {
		d := draftOf()
		d.Typed = strings.Repeat("a", 39) + "b"
		view := fourSeats()
		view.Screen, view.New = screenAt(t, fmt.Sprint(width)), d
		for number := 5; number <= 20; number++ {
			view.Seats = append(view.Seats, Seat{Number: number, Name: fmt.Sprint(number), Word: "idle"})
		}
		lines := Lines(view, width, 20)
		if !strings.Contains(strings.Join(lines, "\n"), "b▏") || len(lines) > 18 || len(view.Seats) != 20 || len(d.Typed) != 40 {
			t.Fatalf("at width %d:\n%s", width, strings.Join(lines, "\n"))
		}
		for _, line := range lines {
			if terminal.Cells(line) > width {
				t.Errorf("at width %d: %q", width, line)
			}
		}
	}
}
