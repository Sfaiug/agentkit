package menu

import "slices"

// Step is the row by rows on from cursor in the order the screen draws them, project by project
// (seatOrder), held at the first and the last, from the first seat where cursor is none of them;
// "" where there are none.
func Step(seats []Seat, switches map[string]int, cursor string, by int) string {
	order := seatOrder(seats, switches)
	if len(order) == 0 {
		return ""
	}
	at := slices.Index(order, cursor)
	if at < 0 {
		at = max(0, slices.IndexFunc(order, func(name string) bool { _, heading := switches[name]; return !heading }))
	}
	return order[min(max(at+by, 0), len(order)-1)]
}
