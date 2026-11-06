package motion

import "time"

// Toggle is how long a mark takes to fill or to empty, half way for the first half of it.
const Toggle = 80 * time.Millisecond

// halves is each mark half way between empty and full.
var halves = map[any]string{"□": "▣", "■": "▣", "○": "◉", "●": "◉"}

// Mark is mark, drawn for key, as it shows now (motion.toggled): one that filled or emptied while
// the screen was up goes through its half for the first half of Toggle, then is as drawn.
func (c *Clock) Mark(key, mark string) string {
	before, moved := c.Moved(key, mark, Toggle)
	if half, ok := halves[mark]; ok && halves[before] != "" && moved < 0.5 {
		return half
	}
	return mark
}
