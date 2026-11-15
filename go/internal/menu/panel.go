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
	lines := []string{panelHeader(title, clock, s.LayoutWidth()), s.Styled(strings.Repeat(rule, s.LayoutWidth()), "dim")}
	lines = append(append(lines, body...), "")
	if keys == "" {
		return lines
	}
	return append(lines, keyLine(s, keys, s.Width(), "")...)
}

// panelHeader is `agentkit`, the screen name after it and the clock at the right.  The title gives
// way, never the clock: a name too wide sheds its first parts, where you came from, then what is
// left is cut, to leave the clock and one space whole.
func panelHeader(name, clock string, room int) string {
	if room <= terminal.Cells(clock) {
		return terminal.Cut(clock, room)
	}
	parts := []string{"agentkit"}
	if name != "" {
		parts = append(parts, strings.Split(name, " · ")...)
	}
	for len(parts) > 2 && terminal.Cells(strings.Join(parts, " · ")) > room-terminal.Cells(clock)-1 {
		parts = append(parts[:1], parts[2:]...)
	}
	title := terminal.Cut(strings.Join(parts, " · "), room-terminal.Cells(clock)-1)
	return title + strings.Repeat(" ", room-terminal.Cells(title)-terminal.Cells(clock)) + clock
}
