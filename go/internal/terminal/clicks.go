package terminal

// Clicks are a screen's own (Python's terminal.clicks_its_own): the left button coming up is a
// click only where it went down on that screen, so a press meant for the screen before, or one
// that goes down here and comes up on the next, picks nothing.  Each screen keeps its own, from
// the zero value as it opens.
type Clicks struct{ pressed bool }

// Click is whether mouse ends a click begun on this screen; every pointer event goes through it,
// so it sees each press.
func (c *Clicks) Click(mouse Mouse) bool {
	if mouse.Button&3 != 0 || mouse.Button&(32|64) != 0 {
		return false // another button, a move or the wheel
	}
	was := c.pressed
	c.pressed = !mouse.Released
	return was && mouse.Released
}
