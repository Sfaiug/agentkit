package menu

import (
	"agentkit/internal/motion"
	"agentkit/internal/terminal"
)

// CatalogWaiting keeps the frame, usage and back key up while an adapter is asked, and says under
// them what for, doing, a spinner turning beside it (menu.waited).
func CatalogWaiting(s terminal.Screen, title, clock, doing string, cells []Cell, moves *motion.Clock) []string {
	body := []string{"", "  " + moves.Spinner(s) + " " + s.Styled(terminal.Cut(doing, s.LayoutWidth()-4), "dim")}
	room := s.Height() - len(Panel(s, title, clock, body, "esc back"))
	usage := usageLines(s, cells, s.LayoutWidth())
	if len(usage) == 0 || len(usage) > room {
		usage = nil
		if room > 0 {
			usage = usageSummary(cells, s.LayoutWidth(), room)
		}
	}
	lines := Panel(s, title, clock, append(usage, body...), "esc back")
	lines[1] = moves.WaitingRule(s, s.LayoutWidth())
	return lines
}

// WaitingBack is whether mouse is on `esc back`, the last of CatalogWaiting's lines, where it is
// drawn (terminal.Under): a click there goes back, as Esc does (menu.waited).
func WaitingBack(lines []string, mouse terminal.Mouse) bool {
	if mouse.Row != len(lines) {
		return false
	}
	last := lines[len(lines)-1]
	at, on := terminal.Under(last, mouse.Column, [2]int{1, terminal.Cells(last)})
	return on && at == 0
}
