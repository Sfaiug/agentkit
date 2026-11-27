package terminal

import (
	"regexp"
	"strings"
	"testing"
)

// A cell on a glow's background with no blue, as `needs you`'s has, comes up out of it from its own
// colour: the background's 0 is a channel, no reset (Python's tests/test_page_comes_up.py).
func TestACellOnABackgroundComesUpOutOfItFromItsOwnColour(t *testing.T) {
	screen := Screen{depth: 24}
	word := screen.Styled("x", "needs you")
	tone := regexp.MustCompile(`\x1b\[(38;2;[\d;]+)mx`)
	// #d79200 half way to black, and to the background after the word's own colour, in its code,
	// as a glow writes it
	for line, want := range map[string]string{word: "38;2;108;73;0",
		strings.Replace(word, "m", ";48;2;64;48;0m", 1): "38;2;140;97;0"} {
		if got := tone.FindAllStringSubmatch(screen.Fade(line, 0.5), -1); len(got) != 1 || got[0][1] != want {
			t.Errorf("%q faded half way: %q, want %s before its x", line, got, want)
		}
	}
}
