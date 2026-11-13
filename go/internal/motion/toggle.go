package motion

import "time"

// Toggle is how long a mark takes to fill or to empty, half way for the first half of it.
const Toggle = 80 * time.Millisecond

// halves is each mark half way between empty and full: its full shape.
var halves = map[any]string{"□": "■", "■": "■", "○": "●", "●": "●"}

// Mark is mark, drawn in kind for key, as it shows now and what it is drawn in (motion.toggled):
// one that filled or emptied while the screen was up is its full shape for the first half of
// Toggle, dim as its open one is, then as drawn.
func (c *Clock) Mark(key, mark, kind string) (string, string) {
	before, moved := c.Moved(key, mark, Toggle)
	if full, ok := halves[mark]; ok && halves[before] != "" && moved < 0.5 {
		return full, "dim"
	}
	return mark, kind
}
