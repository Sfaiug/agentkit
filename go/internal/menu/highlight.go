package menu

import (
	"slices"

	"agentkit/internal/terminal"
)

// Highlight keeps the seat by name across readings. Moving by row opens its line; a page turn
// closes it, and pointing away hides the highlight without losing its place.  Pointer is where the
// pointer was read last, the zero Mouse once a key moves the highlight or before it moved.
type Highlight struct {
	Cursor       string
	Open, Hidden bool
	Pointer      terminal.Mouse
}

// Frame holds the drawing and where its rows, pages and meters take the highlight.
type Frame struct {
	Lines               []string
	spots, order, turns []string
	cursor              string
	page, width, height int
	meters              []meterSpot
}

// Move answers navigation against the frame the owner saw, without reading any record.
func (h *Highlight) Move(key terminal.Key, frame Frame) bool {
	step, turn := 0, 0
	switch {
	case key.Name == "up" || key.Name == "char" && (key.Char == "k" || key.Char == "K"):
		step = -1
	case key.Name == "down" || key.Name == "char" && (key.Char == "j" || key.Char == "J"):
		step = 1
	case key.Name == "left":
		turn = -1
	case key.Name == "right":
		turn = 1
	case key.Name == "pointer":
		mouse := key.Mouse
		if mouse.Button&64 == 0 {
			h.Pointer = mouse
		}
		switch {
		case mouse.Released:
			return true
		case mouse.Button&64 != 0:
			step = mouse.Notches
		default:
			name := ""
			if mouse.Column <= frame.width && mouse.Row > 0 && mouse.Row <= len(frame.spots) {
				name = frame.spots[mouse.Row-1]
			}
			h.Cursor, h.Open, h.Hidden = frame.cursor, name != "", name == ""
			if name != "" {
				h.Cursor = name
			}
			return true
		}
	default:
		return false
	}
	h.Cursor, h.Hidden, h.Pointer = frame.cursor, false, terminal.Mouse{}
	if step != 0 {
		if len(frame.order) > 0 {
			at := max(0, slices.Index(frame.order, frame.cursor))
			h.Cursor = frame.order[max(0, min(at+step, len(frame.order)-1))]
		}
		h.Open = true
	} else {
		for at := frame.page + turn; at >= 0 && at < len(frame.turns); at += turn {
			if frame.turns[at] != "" {
				h.Cursor = frame.turns[at]
				break
			}
		}
		h.Open = false
	}
	return true
}

func seatOrder(seats []Seat) []string {
	var order []string
	for _, project := range projects(seats) {
		for _, seat := range project.seats {
			order = append(order, seat.Name)
		}
	}
	return order
}

func pageTurns(pages [][]row) []string {
	var turns []string
	seen := map[string]bool{}
	for _, lines := range pages {
		first := ""
		for _, each := range lines {
			if each.seat != "" && !seen[each.seat] {
				if first == "" {
					first = each.seat
				}
				seen[each.seat] = true
			}
		}
		turns = append(turns, first)
	}
	return turns
}
