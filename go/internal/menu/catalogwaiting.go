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
