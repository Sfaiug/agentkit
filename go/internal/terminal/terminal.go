// Package terminal handles presentation: widths, wrapping, fitted columns and the state words'
// glyphs and colours, and the keyboard of a screen that takes the terminal.  The one host tool it
// asks is tmux, for what the terminal of the client it runs under takes.
package terminal

import (
	"io"
	"math"
	"os"
	"regexp"
	"strconv"
	"strings"
)

// A style is a word's glyph, its ASCII stand-in, its role of the theme, its eight-colour tone and
// its emphasis.  `dim` is a note beside a row and `FAIL` a verdict, no state; `idle` is drawn
// as dim is.
type style struct{ glyph, ascii, colour, tone, emphasis string }

var styles = map[string]style{
	"needs you":    {"!", "!", "warning", "33", "1"},
	"working":      {"●", "*", "accent", "36", ""},
	"done":         {"✓", "v", "success", "32", ""},
	"out of usage": {"○", "o", "error", "31", ""},
	"FAIL":         {"×", "x", "error", "31", ""},
	"idle":         {"○", "o", "dim", "37", "2"},
	"dim":          {"·", ".", "dim", "37", "2"},
	"quiet":        {"", "", "dim", "37", ""},
}

// kinds are the roles a screen asks Styled for, each the word whose colour it is.
var kinds = map[string]string{"accent": "working", "amber": "needs you"}

// colourOf is a word's colour in a theme: a role's (roles), a state word's, or a kind's.
func colourOf(word string, in theme) string {
	if _, ok := roles[word]; ok {
		return roles[word][in]
	}
	if role, ok := kinds[word]; ok {
		word = role
	}
	return roles[styles[word].colour][in]
}

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

// A Screen is one output's colour depth, background, glyphs and size, read once: a screen asks for
// a colour by its role and a glyph by its word, never an RGB or a code.
type Screen struct {
	depth, width, height int
	ascii                bool
	theme                theme
}

func For(out io.Writer) Screen {
	return Screen{depth: depth(out, false), width: width(out), ascii: !utf8()}
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

// depth is the colours out takes: none off a terminal, under NO_COLOR or a dumb TERM; true colour
// where COLORTERM says so or rgb, a terminal's own features, does; else terminfo's count.
func depth(out io.Writer, rgb bool) int {
	file, ok := out.(*os.File)
	term := os.Getenv("TERM")
	_, noColor := os.LookupEnv("NO_COLOR")
	if !ok || !isTerminal(file) || noColor || term == "" || term == "dumb" {
		return 0
	}
	if color := strings.ToLower(os.Getenv("COLORTERM")); color == "truecolor" || color == "24bit" || rgb {
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

// Height is the terminal's rows, known once a Keyboard has said what the terminal is.
func (s Screen) Height() int {
	return s.height
}

// ContentWidth is the room a listing lays out in: the terminal's, capped at 100 columns.
func (s Screen) ContentWidth() int {
	return max(1, min(s.width, 100))
}

// Styled is text in a state word's colour, or dim, or a role's (kinds), or a caller's own `#RRGGBB`,
// in this screen's theme.
func (s Screen) Styled(text, word string) string {
	if role, ok := kinds[word]; ok {
		word = role
	}
	look, rgb := s.lookOf(word)
	if s.depth == 0 || text == "" {
		return text
	}
	code := look.tone
	switch s.depth {
	case 24:
		code = "38;2;" + strings.Join(channels(rgb), ";")
	case 256:
		code = "38;5;" + strconv.Itoa(xterm(rgb))
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
