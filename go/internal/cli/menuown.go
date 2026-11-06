package cli

import (
	"slices"

	"agentkit/internal/menu"
)

// ownSeat is whether the seat a popup is over has a row, the one seat its x acts on whichever row
// is highlighted (the owner, 27 Oct 2026), and whether that seat is done: x closes a done one at
// once, with nothing left to ask, and asks about any other under its row (menu.loop).
func ownSeat(seats []menu.Seat, name string) (found, done bool) {
	at := slices.IndexFunc(seats, func(each menu.Seat) bool { return each.Name == name })
	return at >= 0, at >= 0 && seats[at].Word == "done"
}
