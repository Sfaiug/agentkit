package terminal

import (
	"fmt"
	"math"
	"strconv"
	"strings"
)

// lookOf is a word's style and its colour on this screen, a `#RRGGBB` taking its own and the
// nearest of the eight basic ones.
func (s Screen) lookOf(word string) (style, string) {
	rgb, own := strings.CutPrefix(word, "#")
	if !own {
		return styles[word], colourOf(word, s.light).rgb
	}
	tone := 30
	for i, text := range channels(rgb) {
		if value, _ := strconv.Atoi(text); value >= 128 {
			tone += 1 << i
		}
	}
	return style{tone: strconv.Itoa(tone)}, rgb
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
// screen's background, or with a negative one that far toward its foreground, lit.
func (s Screen) faded(word string, amount float64) string {
	if role, ok := kinds[word]; ok {
		word = role
	}
	_, rgb := s.lookOf(word)
	to := 0.0
	if s.light {
		to = 255
	}
	if amount < 0 {
		to, amount = 255-to, -amount
	}
	out := "#"
	for _, text := range channels(rgb) {
		value, _ := strconv.Atoi(text)
		out += fmt.Sprintf("%02x", int(math.RoundToEven(float64(value)*(1-amount)+to*amount)))
	}
	return out
}

// ShareLine is a smooth line size cells long, share of it (0 to 1) full: `━` in word's colour, with
// a half cell `╸` where the share ends inside one; the rest is a dim `─`.  Without colour the shapes
// carry it, and without UTF-8 it is `===------`.
func (s Screen) ShareLine(share float64, size int, word string) string {
	return s.GlidingLine(share, share, 1, false, size, word)
}

// GlidingLine is ShareLine on its way there (motion.growing): moved (0 to 1) of the way from the
// share it stood at, its first cells as the whole line draws them and the cells it shrinks from
// full in word's colour, the rest the empty track.  While lit, where colour can move, its head is
// half way from word's colour to the foreground.
func (s Screen) GlidingLine(from, share, moved float64, lit bool, size int, word string) string {
	full, half, empty := "━", "╸", "─"
	halves := int(math.RoundToEven(float64(2*size) * share))
	if s.ascii {
		full, half, empty = "=", "-", "-"
		halves = 2 * int(math.RoundToEven(float64(size)*share))
	}
	ends := (halves + 1) / 2
	start := math.RoundToEven(float64(size) * from)
	head := int(math.RoundToEven(start + (float64(ends)-start)*moved))
	cells := make([]string, head)
	var line strings.Builder
	for n := range head {
		cells[n] = full
		if halves%2 == 1 && n == ends-1 && n == head-1 {
			cells[n] = half
		}
		if s.depth > 8 {
			ink := word
			if lit && n == head-1 {
				ink = s.faded(word, -0.5)
			}
			line.WriteString(s.Styled(cells[n], ink))
		}
	}
	if s.depth <= 8 {
		line.WriteString(s.Styled(strings.Join(cells, ""), word))
	}
	return line.String() + s.Styled(strings.Repeat(empty, size-head), "dim")
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
