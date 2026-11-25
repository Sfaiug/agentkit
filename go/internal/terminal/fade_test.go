package terminal

import (
	"regexp"
	"strings"
	"testing"
)

// A cell on a glow's background with no blue, as `needs you`'s has, comes up from its own colour:
// the background's 0 is a channel, no reset (Python's tests/test_page_comes_up.py).
func TestACellOnABackgroundComesUpFromItsOwnColour(t *testing.T) {
	screen := Screen{depth: 24}
	word := screen.Styled("x", "needs you")
	tone := regexp.MustCompile(`\x1b\[(38;2;[\d;]+)mx`)
	// the background after the word's own colour, in its code, as a glow writes it
	for _, line := range []string{word, strings.Replace(word, "m", ";48;2;64;48;0m", 1)} {
		if got := tone.FindAllStringSubmatch(screen.Fade(line, 0.5), -1); len(got) != 1 || got[0][1] != "38;2;108;73;0" {
			t.Errorf("%q faded half way: %q, want 38;2;108;73;0 before its x", line, got)
		}
	}
}
