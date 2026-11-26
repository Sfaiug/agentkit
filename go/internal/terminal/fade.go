package terminal

import (
	"fmt"
	"maps"
	"math"
	"regexp"
	"strconv"
	"strings"
)

var sgr = regexp.MustCompile(`\x1b\[([0-9;]*)m`)

// Fade is text as a draw wrote it, every colour in it and the foreground its plain cells take, the
// theme's text, amount (0 to 1) of the way to the background each cell sets, the screen's where it
// sets none, that background as it is: a page coming up out of it as it opens, the line a row
// opens, and a label on the highlight out of the highlight.  Where colour cannot move it is as it is.
func (s Screen) Fade(text string, amount float64) string {
	if amount <= 0 || !s.Moves() {
		return text
	}
	numbers := func(role string) []int {
		var out []int
		for _, part := range channels(s.colour(role)) {
			n, _ := strconv.Atoi(part)
			out = append(out, n)
		}
		return out
	}
	unset := map[int][]int{38: numbers("text"), 48: numbers("background")}
	inks := maps.Clone(unset) // the text's colour (38) and the background's (48) so far
	tone := func() string {
		mixed := make([]int, 3)
		for i := range mixed {
			mixed[i] = int(math.RoundToEven(float64(inks[38][i])*(1-amount) + float64(inks[48][i])*amount))
		}
		return "\x1b[" + s.ink(fmt.Sprintf("%02x%02x%02x", mixed[0], mixed[1], mixed[2]), "38") + "m"
	}
	var out strings.Builder
	out.WriteString(tone())
	at := 0
	for _, code := range sgr.FindAllStringSubmatchIndex(text, -1) {
		// the colours this code leaves, as Styled, Highlight and Selected write them
		parts := strings.Split(text[code[2]:code[3]], ";")
		number := func(i int) int { n, _ := strconv.Atoi(parts[i]); return n }
		for i := 0; i < len(parts); i++ {
			switch first := number(i); {
			case first == 0:
				inks = maps.Clone(unset)
			case first == 39 || first == 49:
				inks[first-1] = unset[first-1]
			case (first == 38 || first == 48) && i+4 < len(parts) && parts[i+1] == "2":
				// its channels are read past whole: a 0 among them is no reset
				inks[first] = []int{number(i + 2), number(i + 3), number(i + 4)}
				i += 4
			}
		}
		out.WriteString(text[at:code[1]] + tone())
		at = code[1]
	}
	return out.String() + text[at:] + "\x1b[0m"
}
