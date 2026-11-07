package cli

import (
	"strings"
	"unicode"
)

// pipeTakes is whether Python's menu, reading a pipe, takes key on the frame it drew (menu.loop):
// a seat's number, n, c, p while a past seat is listed, x in a popup over its own seat's row, and
// j or k while a seat has a row, as Python then may cut its frame into pages by a layout Go's does
// not draw; a frame of only its empty row never is.  Each is still Python's to answer.
func pipeTakes(key string, shown *reading, own string) bool {
	switch key {
	case "n", "c":
		return true
	case "p":
		return len(shown.past) > 0
	case "x":
		found, _ := ownSeat(shown.seats, own)
		return found
	case "j", "k":
		return len(shown.seats) > 0
	}
	return strings.IndexFunc(key, func(r rune) bool { return !unicode.IsDigit(r) }) < 0
}
