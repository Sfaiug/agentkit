package menu

import "slices"

// Step is the seat by rows on from cursor in the order the screen draws them, project by project,
// held at the first and the last, from the first where cursor is none of them; "" where there are none.
func Step(seats []Seat, cursor string, by int) string {
	var order []string
	for _, project := range grouped(seats) {
		for _, seat := range project.seats {
			order = append(order, seat.Name)
		}
	}
	if len(order) == 0 {
		return ""
	}
	at := max(0, slices.Index(order, cursor))
	return order[min(max(at+by, 0), len(order)-1)]
}
