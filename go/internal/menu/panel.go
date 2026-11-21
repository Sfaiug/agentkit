package menu

import (
	"strings"

	"agentkit/internal/terminal"
)

// Panel is a sub-screen in the menu's frame, with the key line always last: none where no key
// does anything, as on a report printed once.
func Panel(s terminal.Screen, title, clock string, body []string, keys string) []string {
	rule := "─"
	if s.ASCII() {
		rule = "-"
	}
	lines := []string{panelHeader(s, title, clock, s.LayoutWidth()), s.Styled(strings.Repeat(rule, s.LayoutWidth()), "border")}
	lines = append(append(lines, body...), "")
	if keys == "" {
		return lines
	}
	return append(lines, keyLine(s, keys, s.Width(), "")...)
}

// matrixPanel is a matrix screen drawn as Panel draws it: its page from top, each line's row and
// cells (spots), and where its key line's items are, for a click to press their keys (Pressed).
func matrixPanel(s terminal.Screen, title, clock string, body []string, keys string, top int, spots []matrixRow) MatrixFrame {
	lines, keyed := Panel(s, title, clock, body, keys), keyLine(s, keys, s.Width(), "")
	scrolled := s.Scrolled(len(lines))
	return MatrixFrame{Lines: lines, Top: top, spots: spots, scrolled: scrolled,
		keySpots: spotted(keyed, len(lines)-len(keyed)+1-scrolled, s.LayoutWidth())}
}

// panelHeader is `agentkit`, the screen name after it and the clock at the right.  The title gives
// way, never the clock: a name too wide sheds its first parts, where you came from, then what is
// left is cut, to leave the clock and one space whole.
func panelHeader(s terminal.Screen, name, clock string, room int) string {
	if room <= terminal.Cells(clock) {
		return s.Styled(terminal.Cut(clock, room), "muted")
	}
	parts := []string{"agentkit"}
	if name != "" {
		parts = append(parts, strings.Split(name, " · ")...)
	}
	for len(parts) > 2 && terminal.Cells(strings.Join(parts, " · ")) > room-terminal.Cells(clock)-1 {
		parts = append(parts[:1], parts[2:]...)
	}
	return titled(s, terminal.Cut(strings.Join(parts, " · "), room-terminal.Cells(clock)-1), clock, room)
}

// titled is a header room cells wide: title at the left, `agentkit` as it is and the screen's name
// after it muted, and the clock muted at the right.
func titled(s terminal.Screen, title, clock string, room int) string {
	head, name := title, ""
	if rest, whole := strings.CutPrefix(title, "agentkit"); whole {
		head, name = "agentkit", rest
	}
	return head + s.Styled(name, "muted") + strings.Repeat(" ", room-terminal.Cells(title)-terminal.Cells(clock)) +
		s.Styled(clock, "muted")
}
