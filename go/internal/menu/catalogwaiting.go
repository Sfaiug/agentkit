package menu

import (
	"agentkit/internal/motion"
	"agentkit/internal/terminal"
)

// CatalogWaiting keeps the frame, usage and back key up while a plugin's models are read.
func CatalogWaiting(s terminal.Screen, title, clock string, cells []Cell, moves *motion.Clock) []string {
	body := []string{""}
	for _, line := range terminal.Wrap("Reading models", max(1, s.LayoutWidth()-2)) {
		body = append(body, "  "+line)
	}
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
