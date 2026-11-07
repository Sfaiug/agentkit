package cli

import (
	"cmp"

	"agentkit/internal/menu"
	"agentkit/internal/terminal"
)

// fieldKey is what a key does in the field open under the page's row (terminal.field): Enter
// gives the row's Field what was typed, said under the rows, and shuts the field, as Esc does
// with nothing given; Backspace takes the last character back, and a key that types nothing,
// an arrow or the pointer, is let go.
func fieldKey(view *menu.Page, key terminal.Key) {
	switch typed := []rune(*view.Typed); key.Name {
	case "enter":
		view.Said, view.Typed = view.Rows[view.At].Field(string(typed)), nil
	case "esc":
		view.Typed = nil
	case "backspace":
		*view.Typed = string(typed[:max(0, len(typed)-1)])
	case "char", "space":
		*view.Typed += cmp.Or(key.Char, " ")
	}
}
