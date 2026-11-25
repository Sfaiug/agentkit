package menu

import (
	"fmt"
	"math"
	"slices"
	"strconv"

	"agentkit/internal/motion"
	"agentkit/internal/terminal"
)

// barred is whether a seat's row draws its progress (menu.last_column): one with a plan, or working,
// while it is neither idle nor out of usage.
func barred(seat Seat) bool {
	return seat.Word != "idle" && seat.Word != "out of usage" && (seat.Total > 0 || seat.Word == "working")
}

// moving is the seats as the clock has them this frame: a working seat's mark breathing, on the row
// lit the highlight's band under it, and each line grown in one after another down the screen as it opens, or, where its plan moved while the
// screen was up, gliding from where it stood there, its head lit half way to the foreground
// (motion.growing); a working seat's line, once there, its tip breathing with its mark.
func moving(s terminal.Screen, seats []Seat, clock *motion.Clock, lit string) []Seat {
	seats = slices.Clone(seats)
	nth := 0
	for i := range seats {
		seat := &seats[i]
		word, bright := seat.Word, seat.Name == lit
		breathing := func(glyph string) string { return clock.Breathing(s, glyph, word, bright) }
		if word == "working" {
			seat.mark = breathing(s.Glyph(word))
		}
		if !barred(*seat) {
			continue
		}
		seat.moved = clock.Grown(nth)
		nth++
		before, moved := clock.Moved("plan "+seat.Name, [2]int{seat.Done, seat.Total}, motion.Glide)
		if was, ok := before.([2]int); ok && was[1] > 0 {
			seat.from, seat.moved = float64(was[0])/float64(was[1]), moved
			if moved < 1 {
				seat.tip = func(cell string) string { return s.Tinted(cell, word, -0.5, bright) }
			}
			if seat.counted = seat.Done; was[1] == seat.Total && was[0] < seat.Done {
				seat.counted = was[0] // its count counts on with it
			}
		}
		if word == "working" && seat.moved == 1 {
			seat.tip = breathing
		}
	}
	return seats
}

// withTasks is said, then how many tasks the seat has in flight, ` · 2 tasks`, `, 2 tasks` without
// UTF-8, or that count alone where nothing is said, `2 tasks` (terminal.with_tasks): a row's last
// column says it whatever its word.  Where room cells do not hold it the count gives way, said alone;
// a negative room holds all.
func withTasks(s terminal.Screen, said string, seat Seat, room int) string {
	n, going := len(seat.Tasks), said
	if n > 0 {
		count := strconv.Itoa(n) + " task" + map[bool]string{true: "s"}[n != 1]
		going = count
		if said != "" {
			going = said + map[bool]string{true: ", ", false: " · "}[s.ASCII()] + count
		}
	}
	if room >= 0 && terminal.Cells(going) > room {
		return said
	}
	return going
}

// planBar is a seat's progress in room cells, its count included (terminal.plan_bar): a smooth line
// of how much of its plan is done in its word's colour, then `done of total`, both as far as the line
// has moved (moving; motion.growing, motion.counting), then its tasks in flight (withTasks), as the
// count stays the plan's, all muted; with no plan the same line, nothing done, and `no plan yet`.
// Never under smallest cells of line, the count alone where no cell of it fits, without its tasks
// where they do not fit either.
func planBar(s terminal.Screen, seat Seat, room, smallest int) string {
	count, shown := noPlan, noPlan
	if seat.Total > 0 {
		count = fmt.Sprintf("%d of %d", seat.Done, seat.Total)
		counted := int(math.RoundToEven(float64(seat.counted) + float64(seat.Done-seat.counted)*seat.moved))
		shown = fmt.Sprintf("%*s", len(count), fmt.Sprintf("%d of %d", counted, seat.Total))
	}
	going := withTasks(s, count, seat, -1)
	size := max(smallest, room-terminal.Cells(going)-1)
	if size < 1 {
		return s.Styled(withTasks(s, count, seat, max(room, 0)), "muted")
	}
	return s.GlidingLine(seat.from, float64(seat.Done)/float64(max(seat.Total, 1)), seat.moved, seat.tip, size, seat.Word) + " " +
		s.Styled(shown+going[len(count):], "muted")
}
