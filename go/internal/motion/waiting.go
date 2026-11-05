package motion

import (
	"strings"

	"agentkit/internal/terminal"
)

// WaitingRule is the screen's one waiting indicator, still where the terminal cannot move.
func (c *Clock) WaitingRule(s terminal.Screen, width int) string {
	base, segment := "─", "━"
	if s.ASCII() {
		base, segment = "-", "="
	}
	span, first := max(1, width/8), 0
	if c != nil && s.Moves() {
		c.until(forever)
		first = int(c.at/(2*Frame)) % max(1, width-span+1)
	}
	return s.Styled(strings.Repeat(base, first), "dim") + s.Styled(strings.Repeat(segment, span), "accent") +
		s.Styled(strings.Repeat(base, max(0, width-first-span)), "dim")
}
