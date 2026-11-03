package menu

import (
	"fmt"
	"math"
	"slices"

	"agentkit/internal/motion"
	"agentkit/internal/terminal"
)

// barred is whether a seat's row draws its progress (menu.last_column): one with a plan, or working,
// while it is neither idle nor out of usage.
func barred(seat Seat) bool {
	return seat.Word != "idle" && seat.Word != "out of usage" && (seat.Total > 0 || seat.Word == "working")
}

// moving is the seats as the clock has them this frame: a working seat's mark breathing, and each
// line grown in one after another down the screen as it opens, or, where its plan moved while the
// screen was up, gliding from where it stood there, its head lit (motion.growing).
func moving(s terminal.Screen, seats []Seat, clock *motion.Clock) []Seat {
	seats = slices.Clone(seats)
	nth := 0
	for i := range seats {
		seat := &seats[i]
		if seat.Word == "working" {
			seat.mark = clock.Breathing(s, s.Glyph(seat.Word), seat.Word)
		}
		if !barred(*seat) {
			continue
		}
		seat.moved = clock.Grown(nth)
		nth++
		before, moved := clock.Moved("plan "+seat.Name, [2]int{seat.Done, seat.Total}, motion.Glide)
		if was, ok := before.([2]int); ok && was[1] > 0 {
			seat.from, seat.moved, seat.lit = float64(was[0])/float64(was[1]), moved, moved < 1
			if seat.counted = seat.Done; was[1] == seat.Total && was[0] < seat.Done {
				seat.counted = was[0] // its count counts on with it
			}
		}
	}
	return seats
}

// planBar is a seat's progress in room cells, its count included (terminal.plan_bar): a smooth line
// of how much of its plan is done in its word's colour, then `done of total`, both as far as the line
// has moved (moving; motion.growing, motion.counting); with no plan the same line, nothing done, and `no
// plan yet`.  Never under smallest cells of line, the count alone where no cell of it fits.
func planBar(s terminal.Screen, seat Seat, room, smallest int) string {
	count, shown := noPlan, noPlan
	if seat.Total > 0 {
		count = fmt.Sprintf("%d of %d", seat.Done, seat.Total)
		counted := int(math.RoundToEven(float64(seat.counted) + float64(seat.Done-seat.counted)*seat.moved))
		shown = fmt.Sprintf("%*s", len(count), fmt.Sprintf("%d of %d", counted, seat.Total))
	}
	size := max(smallest, room-terminal.Cells(count)-1)
	if size < 1 {
		return count
	}
	return s.GlidingLine(seat.from, float64(seat.Done)/float64(max(seat.Total, 1)), seat.moved, seat.lit, size, seat.Word) + " " + shown
}
