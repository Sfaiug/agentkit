package terminal

import (
	"cmp"
	"fmt"
	"math"
	"regexp"
	"strconv"
	"strings"
)

// edge is how lit the edge of a subscription's colour washing in is: that far toward the foreground.
const edge = 0.4

var sgr = regexp.MustCompile(`\x1b\[([0-9;]*)m`)

// cube is each channel's steps in xterm's 6x6x6 colour cube.
var cube = [6]int{0, 95, 135, 175, 215, 255}

// Fade is text as a draw wrote it, every colour in it and the foreground its plain cells take,
// amount (0 to 1) of the way to the background: a page coming up out of it as it opens, and the
// line a row opens.  Where colour cannot move it is as it is.
func (s Screen) Fade(text string, amount float64) string {
	if amount <= 0 || !s.Moves() {
		return text
	}
	back := 0
	if s.light {
		back = 255
	}
	tone := func(rgb []int) string {
		if rgb == nil {
			rgb = []int{255 - back, 255 - back, 255 - back}
		}
		mixed := make([]int, 3)
		for i, channel := range rgb {
			mixed[i] = int(math.RoundToEven(float64(channel)*(1-amount) + float64(back)*amount))
		}
		if s.depth == 24 {
			return fmt.Sprintf("\x1b[38;2;%d;%d;%dm", mixed[0], mixed[1], mixed[2])
		}
		return "\x1b[38;5;" + strconv.Itoa(xterm(fmt.Sprintf("%02x%02x%02x", mixed[0], mixed[1], mixed[2]))) + "m"
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
			case first == 38 && i+4 < len(parts) && parts[i+1] == "2":
				rgb, i = []int{number(i + 2), number(i + 3), number(i + 4)}, i+4
			case first == 38 && i+2 < len(parts) && parts[i+1] == "5" && number(i+2) >= 16:
				n := number(i+2) - 16
				rgb, i = []int{cube[n/36%6], cube[n/6%6], cube[n%6]}, i+2
				if n >= 216 {
					grey := 8 + 10*(n-216)
					rgb = []int{grey, grey, grey}
				}
			}
		}
		out.WriteString(text[at:code[1]] + tone(rgb))
		at = code[1]
	}
	return out.String() + text[at:] + "\x1b[0m"
}

// Washed is text drawn in rest ("" plain) with a company's colour washed into it from the left,
// washed (0 to 1) of the way across, a light riding its edge: a subscription's label and meter as
// the pointer comes onto it, or with washed falling, leaves it.  Each letter is written whole from
// its first cell, so a letter two cells wide keeps both and a combining mark its letter.
func (s Screen) Washed(text, colour, rest string, washed float64) string {
	start, end, lift := s.faded(cmp.Or(rest, "dim"), -1), s.faded(colour, 0), s.faded("dim", -1)
	if rest != "" {
		start = s.faded(rest, 0)
	}
	front, taken := washed*float64(Cells(text)+2), 0
	var out strings.Builder
	for _, letter := range text {
		taken += cell(letter)
		// each letter by the last cell it takes, from 0: a combining mark has its letter's
		p := min(1, max(0, front+1-float64(taken)))
		kind := rest
		switch {
		case p >= 1:
			kind = colour
		case p > 0:
			kind = mix(mix(start, end, p), lift, edge*math.Sin(math.Pi*p))
		}
		if kind == "" {
			out.WriteRune(letter)
		} else {
			out.WriteString(s.Styled(string(letter), kind))
		}
	}
	return out.String()
}

// mix is two `#RRGGBB` colours, amount (0 to 1) of the way from the one to the other.
func mix(one, other string, amount float64) string {
	out := "#"
	for i := 1; i < 7; i += 2 {
		a, _ := strconv.ParseUint(one[i:i+2], 16, 8)
		b, _ := strconv.ParseUint(other[i:i+2], 16, 8)
		out += fmt.Sprintf("%02x", int(math.RoundToEven(float64(a)*(1-amount)+float64(b)*amount)))
	}
	return out
}
