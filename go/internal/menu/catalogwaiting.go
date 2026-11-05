package menu

import (
	"agentkit/internal/motion"
	"agentkit/internal/terminal"
)

// CatalogWaiting keeps the frame, usage and back key up while a plugin's models are read.
func CatalogWaiting(s terminal.Screen, title, clock string, cells []Cell, moves *motion.Clock) []string {
	body := usageLines(s, cells, s.LayoutWidth())
	if len(body) == 0 {
		body = usageSummary(cells, s.LayoutWidth(), -1)
	}
	body = append(body, "")
	for _, line := range terminal.Wrap("Reading models", max(1, s.LayoutWidth()-2)) {
		body = append(body, "  "+line)
	}
	lines := Panel(s, title, clock, body, "esc back")
	lines[1] = moves.WaitingRule(s, s.LayoutWidth())
	return lines
}
