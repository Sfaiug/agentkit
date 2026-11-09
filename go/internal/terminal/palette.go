package terminal

import (
	"math"
	"regexp"
	"strconv"
	"strings"
)

// kinds are the roles a screen asks Styled for, each the word whose colour it is.
var kinds = map[string]string{"accent": "working", "amber": "needs you"}

// lightRGB is each word's colour on a light background: Catppuccin Latte, its yellow darkened until
// it reads on white.
var lightRGB = map[string]string{"needs you": "9c6314", "working": "1e66f5", "done": "338022", "FAIL": "d20f39", "idle": "6c6f85", "dim": "6c6f85"}

var backgroundRGB = regexp.MustCompile(`^rgba?:([0-9a-fA-F]+)/([0-9a-fA-F]+)/([0-9a-fA-F]+)`)

// isLight is whether an answer's luma is past half way.
func isLight(answer string) bool {
	found := backgroundRGB.FindStringSubmatch(answer)
	if found == nil {
		return false
	}
	var channel [3]float64
	for i, part := range found[1:] {
		value, err := strconv.ParseUint(part, 16, 64)
		if err != nil {
			return false
		}
		channel[i] = float64(value) / (math.Pow(16, float64(len(part))) - 1)
	}
	return 0.2126*channel[0]+0.7152*channel[1]+0.0722*channel[2] > 0.5
}

// trueColour is whether a tmux client's features say it takes true colour, as tmux and ssh both
// drop COLORTERM on the way in.
func trueColour(features string) bool {
	for _, each := range strings.Split(strings.TrimSpace(features), ",") {
		if each == "RGB" || each == "Tc" {
			return true
		}
	}
	return false
}

// Highlight is a list's highlighted row: with mark, `›` in the accent colour in its first column,
// every row starting on a space it takes, and its text bright; each colour in it ends in a reset,
// and every reset turns the brightness back on.
func (s Screen) Highlight(line string, mark bool) string {
	if mark {
		glyph := "›"
		if s.ascii {
			glyph = ">"
		}
		line = s.Styled(glyph, "accent") + line[1:]
	}
	if s.depth == 0 {
		return line
	}
	return "\x1b[1m" + strings.ReplaceAll(line, "\x1b[0m", "\x1b[0;1m") + "\x1b[0m"
}
