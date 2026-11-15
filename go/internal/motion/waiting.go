package motion

import (
	"strings"

	"agentkit/internal/terminal"
)

// Spin is how long each of the spinner's glyphs shows beside what ak waits on.
const Spin = 2 * Frame

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
	return s.Styled(strings.Repeat(base, first), "border") + s.Styled(strings.Repeat(segment, span), "accent") +
		s.Styled(strings.Repeat(base, max(0, width-first-span)), "border")
}

// Spinner is the glyph turning beside what a wait is for (motion.spinning), in the accent, one each
// Spin from the wait's first draw: the quadrants, which a terminal draws itself whatever its font,
// `|/-\` without UTF-8; still on its first where the terminal cannot move.
func (c *Clock) Spinner(s terminal.Screen) string {
	glyphs := []rune("▖▘▝▗")
	if s.ASCII() {
		glyphs = []rune(`|/-\`)
	}
	turned := 0
	if c != nil && s.Moves() {
		c.until(forever)
		turned = int(c.at/Spin) % len(glyphs)
	}
	return s.Styled(string(glyphs[turned]), "accent")
}
