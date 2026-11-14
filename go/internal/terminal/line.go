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
		return styles[word], colourOf(word, s.theme)
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
// theme's background, or with a negative one that far toward its text, lit.
func (s Screen) faded(word string, amount float64) string {
	if role, ok := kinds[word]; ok {
		word = role
	}
	_, rgb := s.lookOf(word)
	toward := "background"
	if amount < 0 {
		toward, amount = "text", -amount
	}
	to := channels(colourOf(toward, s.theme))
	out := "#"
	for i, text := range channels(rgb) {
		value, _ := strconv.Atoi(text)
		end, _ := strconv.Atoi(to[i])
		out += fmt.Sprintf("%02x", int(math.RoundToEven(float64(value)*(1-amount)+float64(end)*amount)))
	}
	return out
}

// shapes are a bar's: its full, half and empty cell, and how many halves of size cells share (0
// to 1) fills; without UTF-8 whole cells, `=` and `-`.
func (s Screen) shapes(share float64, size int) (full, half, empty string, halves int) {
	if s.ascii {
		return "=", "-", "-", 2 * int(math.RoundToEven(float64(size)*share))
	}
	return "━", "╸", "─", int(math.RoundToEven(float64(2*size) * share))
}

// ShareParts is a bar size cells long, share of it (0 to 1) full, uncoloured: its full part, heavy
// `━` with a half cell `╸` where the share ends inside one, and its empty rest, thin `─`; without
// UTF-8 `===` and `---`.  Every bar is this line, which a terminal draws itself, alike in any one: a
// seat's progress (ShareLine), a subscription's meter and an effort's level (EffortCells).
func (s Screen) ShareParts(share float64, size int) (string, string) {
	full, half, empty, halves := s.shapes(share, size)
	return strings.Repeat(full, halves/2) + strings.Repeat(half, halves%2), strings.Repeat(empty, size-(halves+1)/2)
}

// ShareLine is the bar (ShareParts) its full part in word's colour, the rest dim.
func (s Screen) ShareLine(share float64, size int, word string) string {
	return s.GlidingLine(share, share, 1, false, size, word)
}

// GlidingLine is ShareLine on its way there (motion.growing): moved (0 to 1) of the way from the
// share it stood at, its first cells as the whole line draws them and the cells it shrinks from
// full in word's colour, the rest the empty track.  While lit, where colour can move, its head is
// half way from word's colour to the foreground.
func (s Screen) GlidingLine(from, share, moved float64, lit bool, size int, word string) string {
	full, half, empty, halves := s.shapes(share, size)
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

// EffortCells is an effort's level before its word: the bar (ShareParts) a cell for each of the
// count efforts its model offers, full up to its filled-th and the rest dim, `━━━──` for high of
// five.  One effort is no level to show: no cell.
func (s Screen) EffortCells(count, filled int) []string {
	if count < 2 {
		return nil
	}
	full, rest := s.ShareParts(float64(filled)/float64(count), count)
	cells := strings.Split(full, "")
	for _, cell := range strings.Split(rest, "") {
		cells = append(cells, s.Styled(cell, "dim"))
	}
	return cells
}
