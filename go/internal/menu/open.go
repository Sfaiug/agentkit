package menu

import (
	"strings"
	"unicode/utf8"

	"agentkit/internal/terminal"
)

// Open is the seat Enter or a released left button opens on the frame the owner saw; Enter opens
// nothing where the highlight was hidden (Highlight.Move).
func (f Frame) Open(key terminal.Key) string {
	if key.Name == "enter" && !f.hidden {
		return f.cursor
	}
	if clicked(key) {
		return f.seatAt(key.Mouse)
	}
	return ""
}

// Pressed is key, but for a click on an item of the key line that names a key: that key, as a click
// does what the key would do.
func (spots keySpots) Pressed(key terminal.Key) terminal.Key {
	if at := spots.keyAt(key.Mouse); at >= 0 && clicked(key) && spots[at].key.Name != "" {
		return spots[at].key
	}
	return key
}

// pressing is the key a key-line item names (menu.pressed, menu.matrix_key): `⏎ open` Enter,
// `␣ mark` Space, `esc leave` Esc, an arrow in front of the keys its page turn, any other key of
// one character itself; the page's place between the arrows, and `↑↓←→ move`, none.
func pressing(item string) terminal.Key {
	key, _, _ := strings.Cut(item, " ")
	switch key {
	case "⏎", "enter":
		return terminal.Key{Name: "enter"}
	case "␣", "space":
		return terminal.Key{Name: "space"}
	case "esc":
		return terminal.Key{Name: "esc"}
	case "←", "<":
		return terminal.Key{Name: "left"}
	case "→", ">":
		return terminal.Key{Name: "right"}
	}
	if utf8.RuneCountInString(key) == 1 && (key[0] < '0' || key[0] > '9') {
		return terminal.Key{Name: "char", Char: key}
	}
	return terminal.Key{}
}

// clicked is whether key is the left button coming up, a click.
func clicked(key terminal.Key) bool {
	m := key.Mouse
	return key.Name == "pointer" && m.Released && m.Button&3 == 0 && m.Button&64 == 0
}
