package menu

import (
	"strings"

	"agentkit/internal/terminal"
)

// Panel is a sub-screen in the menu's frame, with the key line always last.
func Panel(s terminal.Screen, title, clock string, body []string, keys string) []string {
	rule := "─"
	if s.ASCII() {
		rule = "-"
	}
	lines := []string{panelHeader(title, clock, s.LayoutWidth()), s.Styled(strings.Repeat(rule, s.LayoutWidth()), "dim")}
	return append(append(append(lines, body...), ""), keyLine(s, keys, s.Width(), "")...)
}

func panelHeader(name, clock string, room int) string {
	if room <= terminal.Cells(clock) {
		return terminal.Cut(clock, room)
	}
	title := "agentkit"
	if name != "" {
		title += " · " + name
	}
	title = terminal.Cut(title, room-terminal.Cells(clock)-1)
	return title + strings.Repeat(" ", room-terminal.Cells(title)-terminal.Cells(clock)) + clock
}
