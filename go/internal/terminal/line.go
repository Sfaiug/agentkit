package terminal

import (
	"cmp"
	"fmt"
	"math"
	"strconv"
	"strings"
)

// lookOf is a word's style, a `#RRGGBB` taking its colour and the nearest of the eight basic ones.
func lookOf(word string) style {
	rgb, own := strings.CutPrefix(word, "#")
	if !own {
		return styles[word]
	}
	tone := 30
	for i, text := range channels(rgb) {
		if value, _ := strconv.Atoi(text); value >= 128 {
			tone += 1 << i
		}
	}
	return style{rgb: rgb, tone: strconv.Itoa(tone)}
}

// LayoutWidth is the room a screen lays out in: the terminal's, up to 120 columns; beyond that the
// margin grows, never the text.
func (s Screen) LayoutWidth() int {
	return max(1, min(s.width, 120))
}

// Pad is text cut to room and filled to it.
func Pad(text string, room int) string {
	text = Cut(text, room)
	return text + strings.Repeat(" ", max(0, room-Cells(text)))
}

// faded is a word's colour, as Styled draws it, or a `#RRGGBB`, amount (0 to 1) of the way to the
// screen's background.
func (s Screen) faded(word string, amount float64) string {
	if role, ok := kinds[word]; ok {
		word = role
	}
	rgb, to := lookOf(word).rgb, 0.0
	if s.light {
		rgb, to = cmp.Or(lightRGB[word], rgb), 255
	}
	out := "#"
	for _, text := range channels(rgb) {
		value, _ := strconv.Atoi(text)
		out += fmt.Sprintf("%02x", int(math.RoundToEven(float64(value)*(1-amount)+to*amount)))
	}
	return out
}

// ShareLine is a smooth line size cells long, share of it (0 to 1) full: `━` in word's colour, on a
// terminal of more than eight colours fading in from half way to its background at the line's
// start to the colour at its tip, with a half cell `╸` where the share ends inside one; the rest is
// a dim `─`.  Without colour the shapes carry it, and without UTF-8 it is `===------`.
func (s Screen) ShareLine(share float64, size int, word string) string {
	return s.GrowingLine(share, 1, size, word)
}

// GrowingLine is ShareLine grown (0 to 1) of the way to its length (motion.growing): its first cells
// as the whole line draws them, the rest the empty track.
func (s Screen) GrowingLine(share, grown float64, size int, word string) string {
	full, half, empty := "━", "╸", "─"
	halves := int(math.RoundToEven(float64(2*size) * share))
	if s.ascii {
		full, half, empty = "=", "-", "-"
		halves = 2 * int(math.RoundToEven(float64(size)*share))
	}
	ends := (halves + 1) / 2
	head := int(math.RoundToEven(float64(ends) * grown))
	rest := strings.Repeat(empty, size-head)
	tip := max(1, ends-1)
	cells := make([]string, head)
	var line strings.Builder
	for n := range head {
		cells[n] = half
		if n < halves/2 {
			cells[n] = full
		}
		if s.depth > 8 {
			amount := 0.0
			if ends > 1 {
				amount = 0.5 * (1 - float64(n)/float64(tip))
			}
			line.WriteString(s.Styled(cells[n], s.faded(word, amount)))
		}
	}
	if s.depth <= 8 {
		line.WriteString(s.Styled(strings.Join(cells, ""), word))
	}
	return line.String() + s.Styled(rest, "dim")
}

// EffortCells is an effort's level before its word, a cell for each of the count its model offers:
// the first filled full and the rest open and dim (`▰▰▰▱▱` for high of five); without UTF-8 `#` and
// `-`.  One effort is no level to show: no cell.
func (s Screen) EffortCells(count, filled int) []string {
	if count < 2 {
		return nil
	}
	full, empty := "▰", "▱"
	if s.ascii {
		full, empty = "#", "-"
	}
	cells := make([]string, count)
	for n := range cells {
		cells[n] = s.Styled(empty, "dim")
		if n < filled {
			cells[n] = full
		}
	}
	return cells
}
