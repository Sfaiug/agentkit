package motion

import (
	"math"
	"time"

	"agentkit/internal/terminal"
)

// Themed is how long a theme chosen takes to come down the screen, its top row to its last.
const Themed = 350 * time.Millisecond

// Turned is what to write over a draw on s while a theme chosen on it comes down it (Python's
// motion.Clock.rise): the rows from the line it has come to down, as painter had them up in the
// theme before, each whole, so every row reads at every frame, the first frame the top row's in
// the new one.  None once the line has passed the last row, a key finished it, or colour cannot
// move.
func (c *Clock) Turned(s terminal.Screen, painter *terminal.Painter) []terminal.Span {
	if c == nil {
		return nil
	}
	if up, on := painter.Holds(); up != nil && on.Theme() != s.Theme() && s.Moves() {
		c.turning = make([]terminal.Span, s.Height())
		for at := range c.turning {
			line := ""
			if at < len(up) {
				line = up[at]
			}
			c.turning[at] = terminal.Span{Row: at + 1, Column: 1, Text: on.Kept(line)}
		}
	}
	before, moved := c.Moved("theme", s.Theme(), Themed)
	// as Python's round, so both put the line on the same row
	below := 1 + max(1, int(math.RoundToEven(float64(len(c.turning))*moved)))
	if before == nil || below > len(c.turning) {
		c.turning = nil
		return nil
	}
	return c.turning[below-1:]
}
