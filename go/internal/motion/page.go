package motion

import "time"

const (
	Rise  = 120 * time.Millisecond // a page takes to come up out of the background, its name written out
	Open  = 120 * time.Millisecond // ... the line under a row the highlight came to takes to come up
	Wash  = 300 * time.Millisecond // ... a subscription's colour takes to wash in under the pointer
	Drain = 200 * time.Millisecond // ... and to drain once the pointer leaves it
)

// Risen is how far a page has come up since it opened, 0 to 1 eased over Rise: its name writing
// itself out in its header and all under that coming up out of the background.  A key finishes it,
// and so does Finish before the first draw, for a page drawn again as it was.
func (c *Clock) Risen() float64 {
	if c == nil || c.grown {
		return 1
	}
	c.until(Rise)
	return Eased(float64(c.at) / float64(Rise))
}
