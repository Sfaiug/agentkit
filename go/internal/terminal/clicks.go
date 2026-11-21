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

// Key reads key for this screen (Python's terminal.read_key): the left button going down is
// remembered and returned as the zero Key so it lights nothing; its release is returned with
// clicked true only where it went down on this screen, and any other button press or release
// becomes "other", taking neither a click nor the highlight.
func (c *Clicks) Key(key Key) (Key, bool) {
	if key.Name != "pointer" || key.Mouse.Button&(32|64) != 0 {
		return key, false
	}
	if key.Mouse.Button&3 == 0 && !key.Mouse.Released {
		c.Click(key.Mouse)
		return Key{}, false
	}
	if c.Click(key.Mouse) {
		return key, true
	}
	return Key{Name: "other"}, false
}
