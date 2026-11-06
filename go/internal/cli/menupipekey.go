package cli

import (
	"slices"
	"strings"
	"unicode"
)

// pipeTakes is whether Python's menu, reading a pipe, takes a line as a key (menu.loop): a seat's
// number, n, c, p, a page turned with j or k, or x in a popup.  Each still is Python's to answer.
func pipeTakes(key string, overlay bool) bool {
	return strings.IndexFunc(key, func(r rune) bool { return !unicode.IsDigit(r) }) < 0 ||
		slices.Contains([]string{"n", "c", "p", "j", "k"}, key) || overlay && key == "x"
}
