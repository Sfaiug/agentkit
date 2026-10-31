// Package terminal handles presentation without invoking host tools: widths,
// wrapping, fitted columns and the state words' glyphs and colours.
package terminal

import (
	"io"
	"os"
	"strconv"
	"strings"
)

// A style is a word's glyph, its ASCII stand-in, its colour on a dark background, its
// eight-colour tone and its emphasis.  `dim` is a note beside a row, no state; `idle` is drawn
// as dim is.
type style struct{ glyph, ascii, rgb, tone, emphasis string }

var styles = map[string]style{
	"needs you": {"!", "!", "f9e2af", "33", "1"},
	"working":   {"●", "*", "89b4fa", "36", ""},
	"done":      {"✓", "v", "a6e3a1", "32", ""},
	"idle":      {"○", "o", "6c7086", "37", "2"},
	"dim":       {"·", ".", "6c7086", "37", "2"},
}

// A Screen is one output's colour depth, glyphs and width, read once.
type Screen struct {
	depth, width int
	ascii        bool
}

func For(out io.Writer) Screen {
	return Screen{depth(out), width(out), !utf8()}
}

// TypedHere is whether a person is at this command's keyboard: agents run ak with no
// terminal on stdin.
func TypedHere() bool {
	return isTerminal(os.Stdin)
}

// Attachable is whether this command can hand its terminal to a seat: its input and its output
// are both one.
func Attachable() bool {
	return isTerminal(os.Stdin) && isTerminal(os.Stdout)
}

func Dim(out io.Writer, text string) string {
	return For(out).Styled(text, "dim")
}

func depth(out io.Writer) int {
	file, ok := out.(*os.File)
	term := os.Getenv("TERM")
	_, noColor := os.LookupEnv("NO_COLOR")
	if !ok || !isTerminal(file) || noColor || term == "" || term == "dumb" {
		return 0
	}
	if color := strings.ToLower(os.Getenv("COLORTERM")); color == "truecolor" || color == "24bit" {
		return 24
	}
	switch colors := terminalColors(term); {
	case colors >= 256:
		return 256
	case colors >= 8:
		return 8
	}
	return 0
}

// width is COLUMNS where it is a positive number, else the terminal's, else 100.
func width(out io.Writer) int {
	if columns, err := strconv.Atoi(os.Getenv("COLUMNS")); err == nil && columns > 0 {
		return columns
	}
	if file, ok := out.(*os.File); ok {
		if columns := columns(file); columns > 0 {
			return columns
		}
	}
	return 100
}

// The caller's locale decides the glyphs: plain C or POSIX asks for ASCII.
func utf8() bool {
	if os.Getenv("LC_ALL") == "" && (os.Getenv("LANG") == "C" || os.Getenv("LANG") == "POSIX") {
		return false
	}
	locale := os.Getenv("LC_ALL")
	for _, name := range []string{"LC_CTYPE", "LANG"} {
		if locale == "" {
			locale = os.Getenv(name)
		}
	}
	return locale == "" || strings.Contains(strings.ReplaceAll(strings.ToLower(locale), "-", ""), "utf8")
}

// Width is the terminal's columns, for a listing that wraps to all of them.
func (s Screen) Width() int {
	return s.width
}

// ContentWidth is the room a listing lays out in: the terminal's, capped at 100 columns.
func (s Screen) ContentWidth() int {
	return max(1, min(s.width, 100))
}

// Styled is text in a state word's colour, or dim.
func (s Screen) Styled(text, word string) string {
	look := styles[word]
	if s.depth == 0 || text == "" {
		return text
	}
	code := look.tone
	switch s.depth {
	case 24:
		code = "38;2;" + strings.Join(channels(look.rgb), ";")
	case 256:
		code = "38;5;" + strconv.Itoa(xterm(look.rgb))
	}
	if (word == "dim" || word == "idle") && s.depth == 8 {
		code = "2"
	} else if look.emphasis != "" {
		code = look.emphasis + ";" + code
	}
	return "\x1b[" + code + "m" + text + "\x1b[0m"
}

func channels(rgb string) []string {
	var parts []string
	for i := 0; i < 6; i += 2 {
		value, _ := strconv.ParseUint(rgb[i:i+2], 16, 8)
		parts = append(parts, strconv.Itoa(int(value)))
	}
	return parts
}

// xterm is the nearest fixed xterm colour, the lower number on a tie: in the cube each
// channel is nearest on its own, and the nearest grey is the one nearest the channels' mean.
func xterm(rgb string) int {
	levels := []int{0, 95, 135, 175, 215, 255}
	var wanted, steps [3]int
	sum := 0
	for i, text := range channels(rgb) {
		wanted[i], _ = strconv.Atoi(text)
		sum += wanted[i]
		for n := range levels {
			if abs(levels[n]-wanted[i]) < abs(levels[steps[i]]-wanted[i]) {
				steps[i] = n
			}
		}
	}
	grey := 0
	for n := range 24 {
		if abs(3*(8+10*n)-sum) < abs(3*(8+10*grey)-sum) {
			grey = n
		}
	}
	distance := func(values [3]int) int {
		total := 0
		for i := range values {
			total += (wanted[i] - values[i]) * (wanted[i] - values[i])
		}
		return total
	}
	level := 8 + 10*grey
	if distance([3]int{level, level, level}) < distance([3]int{levels[steps[0]], levels[steps[1]], levels[steps[2]]}) {
		return 232 + grey
	}
	return 16 + 36*steps[0] + 6*steps[1] + steps[2]
}

func abs(n int) int {
	return max(n, -n)
}

// Glyph is a state word's mark alone.
func (s Screen) Glyph(word string) string {
	if s.ascii {
		return styles[word].ascii
	}
	return styles[word].glyph
}

// StateText is `glyph word`.
func (s Screen) StateText(word string) string {
	return s.Glyph(word) + " " + word
}

// StateCell is a state column's cell: `glyph word` in the state's colour.
func (s Screen) StateCell(word string) string {
	return s.Styled(s.StateText(word), word)
}

// TableRow is fixed columns with two-space gutters and no trailing space: each cell cut,
// then styled, then padded, so the pads land outside the colour escapes.
func (s Screen) TableRow(texts []string, widths []int, words []string) string {
	parts := make([]string, len(texts))
	for i, text := range texts {
		text = Cut(text, widths[i])
		if i < len(words) && words[i] != "" {
			text = s.Styled(text, words[i])
		}
		parts[i] = text + strings.Repeat(" ", max(0, widths[i]-Cells(text)))
	}
	return strings.TrimRight(strings.Join(parts, "  "), " ")
}
