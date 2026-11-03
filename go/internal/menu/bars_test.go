package menu

import (
	"strings"
	"testing"
	"time"

	"agentkit/internal/motion"
)

// row is the drawn line holding that seat's name.
func rowOf(lines []string, name string) string {
	for _, line := range lines {
		if strings.Contains(line, " "+name+" ") {
			return line
		}
	}
	return ""
}

// Each plan's line eases out to its share, its count with it; a done seat's is full, an idle one
// has none, and every bar starts and ends in one column.
func TestEachPlanEasesOutToItsShare(t *testing.T) {
	view := View{Clock: "14:02"}
	for i, each := range []Seat{{Name: "atoll-fix", Word: "working", Done: 3, Total: 7},
		{Name: "atoll-done", Word: "done", Done: 2, Total: 2}, {Name: "atoll-ask", Word: "needs you"},
		{Name: "atoll-rest", Word: "idle", Done: 1, Total: 2}} {
		each.Number, each.Model, each.Checkout = i+1, "Fable 5.1", "/home/acme/code/atoll"
		view.Seats = append(view.Seats, each)
	}
	opening := Lines(view, 100, 30)
	if fix := rowOf(opening, "atoll-fix"); !strings.HasSuffix(fix, "─ 0 of 7") || strings.Contains(fix, "━") {
		t.Fatalf("a screen just up draws no line grown: %q", fix)
	}
	if !Growing(view.Seats, 0) {
		t.Fatal("a screen just up grows")
	}
	view.Up = motion.Grow + time.Second
	if Growing(view.Seats, view.Up) {
		t.Fatal("a screen up a while is still")
	}
	grown := Lines(view, 100, 30)
	fix, done := rowOf(grown, "atoll-fix"), rowOf(grown, "atoll-done")
	if !strings.HasSuffix(fix, "━╸───────────────────────────── 3 of 7") {
		t.Fatalf("%q", fix)
	}
	if !strings.HasSuffix(done, "━ 2 of 2") || strings.Contains(done, "─") {
		t.Fatalf("a done seat's line is full: %q", done)
	}
	column := func(row string) int { return len([]rune(row[:strings.Index(row, "━")])) }
	if column(fix) != column(done) || len([]rune(fix)) != len([]rune(done)) {
		t.Fatalf("bars apart:\n%q\n%q", fix, done)
	}
	for _, name := range []string{"atoll-ask", "atoll-rest"} {
		if row := rowOf(grown, name); strings.ContainsAny(row, "━─") || strings.Contains(row, " of ") {
			t.Fatalf("no plan or at rest, no line: %q", row)
		}
	}
	halfway := rowOf(Lines(View{Clock: view.Clock, Seats: view.Seats, Up: motion.Grow / 2}, 100, 30), "atoll-fix")
	if strings.Count(halfway, "━") == 0 || strings.Count(halfway, "━") >= strings.Count(fix, "━")+1 || !strings.HasSuffix(halfway, " 1 of 7") { // eased(0.5) is a hair under a half, in Python too
		t.Fatalf("half way grown: %q", halfway)
	}
}
