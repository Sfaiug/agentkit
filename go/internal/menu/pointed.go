package menu

import (
	"slices"

	"agentkit/internal/terminal"
)

// seatAt is the seat whose row the pointer is on where that row is drawn (terminal.Under): "" off
// every row, and on the blank past a row's text.
func (f Frame) seatAt(mouse terminal.Mouse) string {
	if mouse.Row <= 0 || mouse.Row > min(len(f.spots), len(f.Lines)) {
		return ""
	}
	if _, on := terminal.Under(f.Lines[mouse.Row-1], mouse.Column); !on {
		return ""
	}
	return f.spots[mouse.Row-1]
}

// A keySpot is an item of the key line on the ak screen: its screen row, its first and last column
// (terminal.KeyItems), and the key a click on it presses (pressing).
type keySpot struct {
	row, first, last int
	key              terminal.Key
}

// keyAt is the item of the key line the pointer is on, -1 for none.
func (f Frame) keyAt(mouse terminal.Mouse) int {
	return slices.IndexFunc(f.keys, func(spot keySpot) bool {
		return mouse.Row == spot.row && mouse.Column >= spot.first && mouse.Column <= spot.last
	})
}
