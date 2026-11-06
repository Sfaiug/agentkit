package cli

import (
	"strings"
	"unicode"
)

// pipeTakes is whether Python's menu, reading a pipe, takes key on the frame it drew (menu.loop):
// a seat's number, n, c, p while a past seat is listed, x in a popup over its own seat's row, and
// j or k while the frame may be cut into pages, taller than the screen but for the prompt and one
// spare line.  Each is still Python's to answer.
func pipeTakes(key string, shown *reading, own string, frame []string, height int) bool {
	switch key {
	case "n", "c":
		return true
	case "p":
		return len(shown.past) > 0
	case "x":
		found, _ := ownSeat(shown.seats, own)
		return found
	case "j", "k":
		return len(frame) > height-2
	}
	return strings.IndexFunc(key, func(r rune) bool { return !unicode.IsDigit(r) }) < 0
}
