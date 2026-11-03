package menu

import (
	"fmt"
	"math"
	"slices"
	"time"

	"agentkit/internal/motion"
	"agentkit/internal/terminal"
)

// barred is whether a seat's row draws its progress (menu.last_column): one with a plan, or working,
// while it is neither idle nor out of usage.
func barred(seat Seat) bool {
	return seat.Word != "idle" && seat.Word != "out of usage" && (seat.Total > 0 || seat.Word == "working")
}

// grownIn is the seats with each line grown as far as a screen up that long has eased it in, one
// line after another down the screen (motion.Grown).
func grownIn(seats []Seat, up time.Duration) []Seat {
	seats = slices.Clone(seats)
	nth := 0
	for i := range seats {
		if barred(seats[i]) {
			seats[i].grown = motion.Grown(up, nth)
			nth++
		}
	}
	return seats
}

// Growing is whether a line of those seats on a screen up that long still grows in.
func Growing(seats []Seat, up time.Duration) bool {
	lines := 0
	for _, seat := range seats {
		if barred(seat) {
			lines++
		}
	}
	return motion.Growing(up, lines)
}

// planBar is a seat's progress in room cells, its count included (terminal.plan_bar): a smooth line
// of how much of its plan is done in its word's colour, then `done of total`, both as far as the line
// has grown in (motion.growing, motion.counting); with no plan the same line, nothing done, and `no
// plan yet`.  Never under smallest cells of line, the count alone where no cell of it fits.
func planBar(s terminal.Screen, seat Seat, room, smallest int) string {
	count, shown := noPlan, noPlan
	if seat.Total > 0 {
		count = fmt.Sprintf("%d of %d", seat.Done, seat.Total)
		counted := int(math.RoundToEven(float64(seat.Done) * seat.grown))
		shown = fmt.Sprintf("%*s", len(count), fmt.Sprintf("%d of %d", counted, seat.Total))
	}
	size := max(smallest, room-terminal.Cells(count)-1)
	if size < 1 {
		return count
	}
	return s.GrowingLine(float64(seat.Done)/float64(max(seat.Total, 1)), seat.grown, size, seat.Word) + " " + shown
}
