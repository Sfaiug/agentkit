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
	opened := time.Now()
	view.Motion = &motion.Clock{}
	view.Motion.Draw(opened)
	opening := Lines(view, 100, 30)
	if fix := rowOf(opening, "atoll-fix"); !strings.HasSuffix(fix, "─ 0 of 7") || strings.Contains(fix, "━") {
		t.Fatalf("a screen just up draws no line grown: %q", fix)
	}
	if _, due := view.Motion.Next(); !due {
		t.Fatal("a screen just up grows")
	}
	halfway := &motion.Clock{}
	halfway.Draw(opened)
	halfway.Draw(opened.Add(motion.Grow / 2))
	view.Motion.Draw(opened.Add(motion.Grow + time.Second))
	grown := Lines(view, 100, 30)
	if _, due := view.Motion.Next(); due {
		t.Fatal("a screen up a while is still")
	}
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
	half := rowOf(Lines(View{Clock: view.Clock, Seats: view.Seats, Motion: halfway}, 100, 30), "atoll-fix")
	if strings.Count(half, "━") == 0 || strings.Count(half, "━") >= strings.Count(fix, "━")+1 || !strings.HasSuffix(half, " 1 of 7") { // eased(0.5) is a hair under a half, in Python too
		t.Fatalf("half way grown: %q", half)
	}
}

// A plan that moves while the screen is up glides to its new length, its count counting on with it,
// and is still once there.
func TestAMovingPlanGlidesThere(t *testing.T) {
	opened, clock := time.Now(), &motion.Clock{}
	seat := Seat{Number: 1, Name: "atoll-fix", Model: "Fable 5.1", Word: "working", Done: 2, Total: 8}
	draw := func(after time.Duration, done int) string {
		seat.Done = done
		clock.Draw(opened.Add(after))
		return rowOf(Lines(View{Seats: []Seat{seat}, Motion: clock}, 100, 30), "atoll-fix")
	}
	draw(0, 2)
	still := draw(time.Hour, 2)
	if got := draw(time.Hour, 6); got != still {
		t.Fatalf("a plan that moved has not begun to: %q", got)
	}
	if got := draw(time.Hour+motion.Glide/2, 6); strings.Count(got, "━") <= strings.Count(still, "━") || !strings.HasSuffix(got, " 4 of 8") {
		t.Fatalf("half way there: %q", got)
	}
	seat.Done = 6
	there := rowOf(Lines(View{Seats: []Seat{seat}}, 100, 30), "atoll-fix")
	if got := draw(time.Hour+motion.Glide, 6); got != there {
		t.Fatalf("there: %q", got)
	}
	if _, due := clock.Next(); due { // nor does its mark breathe, where colour cannot move
		t.Fatal("a line there still moves")
	}
}
