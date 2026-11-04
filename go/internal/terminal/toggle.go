package terminal

import "strings"

// Reverse lights the text the keys act on; a mark uses Toggle's brackets without colour.
func (s Screen) Reverse(text string) string {
	if s.depth == 0 {
		return text
	}
	return "\x1b[7m" + text + "\x1b[0m"
}

// Toggle centres a role mark in its column, bracketed where no colour can reverse it.
func (s Screen) Toggle(mark string, width int, focused bool, kind string) string {
	shown, lead := " "+mark+" ", max(0, (width-3)/2)
	if focused {
		if s.depth == 0 {
			shown = "[" + mark + "]"
		} else {
			shown = s.Reverse(shown)
		}
	} else if kind != "" {
		shown = s.Styled(shown, kind)
	}
	return strings.Repeat(" ", lead) + shown + strings.Repeat(" ", max(0, width-lead-3))
}
