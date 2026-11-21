package terminal

import (
	"fmt"
	"math"
	"regexp"
	"strconv"
	"strings"
)

var sgr = regexp.MustCompile(`\x1b\[([0-9;]*)m`)

// cube is each channel's steps in xterm's 6x6x6 colour cube.
var cube = [6]int{0, 95, 135, 175, 215, 255}

// Fade is text as a draw wrote it, every colour in it and the foreground its plain cells take, the
// theme's text, amount (0 to 1) of the way to the background: a page coming up out of it as
// it opens, and the line a row opens.  Where colour cannot move it is as it is.
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
	back, fore := numbers("background"), numbers("text")
	tone := func(rgb []int) string {
		if rgb == nil {
			rgb = fore
		}
		mixed := make([]int, 3)
		for i, channel := range rgb {
			mixed[i] = int(math.RoundToEven(float64(channel)*(1-amount) + float64(back[i])*amount))
		}
		return "\x1b[" + s.ink(fmt.Sprintf("%02x%02x%02x", mixed[0], mixed[1], mixed[2]), "38") + "m"
	}
	var out strings.Builder
	var rgb []int
	out.WriteString(tone(nil))
	at := 0
	for _, code := range sgr.FindAllStringSubmatchIndex(text, -1) {
		// the colour this code leaves, read back from what Styled and Highlight write
		parts := strings.Split(text[code[2]:code[3]], ";")
		number := func(i int) int { n, _ := strconv.Atoi(parts[i]); return n }
		for i := 0; i < len(parts); i++ {
			switch first := number(i); {
			case first == 0 || first == 39:
				rgb = nil
			case (first == 38 || first == 48) && i+4 < len(parts) && parts[i+1] == "2":
				if first == 38 {
					rgb = []int{number(i + 2), number(i + 3), number(i + 4)}
				}
				i += 4
			case (first == 38 || first == 48) && i+2 < len(parts) && parts[i+1] == "5":
				if first == 38 && number(i+2) >= 16 {
					n := number(i+2) - 16
					rgb = []int{cube[n/36%6], cube[n/6%6], cube[n%6]}
					if n >= 216 {
						grey := 8 + 10*(n-216)
						rgb = []int{grey, grey, grey}
					}
				}
				i += 2
			}
		}
		out.WriteString(text[at:code[1]] + tone(rgb))
		at = code[1]
	}
	return out.String() + text[at:] + "\x1b[0m"
}
