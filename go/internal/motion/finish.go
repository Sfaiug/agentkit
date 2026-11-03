package motion

// Finish settles the motion a key interrupts. Breathing continues, and a later record change can
// move afresh; the screen's opening progress lines have already reached their lengths.
func (c *Clock) Finish() {
	c.grown = true
	for key, each := range c.seen {
		each.before = nil
		c.seen[key] = each
	}
}
