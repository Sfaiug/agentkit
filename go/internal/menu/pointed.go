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

// A keySpot is an item of a drawn key line: its screen row, its first and last column
// (terminal.KeyItems), and the key a click on it presses (pressing).
type keySpot struct {
	row, first, last int
	key              terminal.Key
}

// keySpots is each item of a screen's key line that presses a key.
type keySpots []keySpot

// spotted is where each item of the key line `keys`, drawn to `layout`, is, its first line the
// screen's row `row`: an item that presses nothing is none, so the pointer lights it no more than
// a click acts on it (terminal.key_spans).
func spotted(keys []string, row, layout int) keySpots {
	var spots keySpots
	for at, line := range keys {
		for _, item := range terminal.KeyItems(line, layout) {
			if key := pressing(item.Text); key.Name != "" {
				spots = append(spots, keySpot{row + at, item.First, item.Last, key})
			}
		}
	}
	return spots
}

// light puts the item of the key line the pointer is on, of the screen `lines` from its first row,
// on the selection: the pointer lights what a click there acts on (terminal.lit).
func (spots keySpots) light(s terminal.Screen, lines []string, mouse terminal.Mouse) {
	if at := spots.keyAt(mouse); at >= 0 {
		if spot := spots[at]; spot.row > 0 && spot.row <= len(lines) {
			lines[spot.row-1] = s.Selected(lines[spot.row-1], spot.first, spot.last)
		}
	}
}

// keyAt is the item of the key line the pointer is on, -1 for none.
func (spots keySpots) keyAt(mouse terminal.Mouse) int {
	return slices.IndexFunc(spots, func(spot keySpot) bool {
		return mouse.Row == spot.row && mouse.Column >= spot.first && mouse.Column <= spot.last
	})
}
