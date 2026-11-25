// Package terminal handles presentation: widths, wrapping, fitted columns and the state words'
// glyphs and colours, and the keyboard of a screen that takes the terminal.  The one host tool it
// asks is tmux, for what the terminal of the client it runs under takes.
package terminal

import (
	"fmt"
	"io"
	"math"
	"os"
	"regexp"
	"strconv"
	"strings"
)

// A style is a word's glyph, its ASCII stand-in, its role of the theme, its eight-colour tone and
// its emphasis.  `dim` is a note beside a row and `FAIL` a verdict, no state; `idle` is drawn
// as dim is; `muted`, `border` and `info` are the roles of text no state's colour is
// (docs/cli-design.md, Colour), at eight colours plain, faint as a note and cyan.  A note is
// its colour alone above eight colours: faint would draw it darker, a colour of neither theme.
type style struct{ glyph, ascii, colour, tone, emphasis string }

var styles = map[string]style{
	"needs you":    {"!", "!", "warning", "33", "1"},
	"working":      {"●", "*", "accent", "36", ""},
	"done":         {"✓", "v", "success", "32", ""},
	"out of usage": {"○", "o", "error", "31", ""},
	"FAIL":         {"×", "x", "error", "31", ""},
	"idle":         {"○", "o", "dim", "37", "2"},
	"dim":          {"·", ".", "dim", "37", ""},
	"quiet":        {"", "", "dim", "37", ""},
	"muted":        {"", "", "muted", "39", ""},
	"border":       {"", "", "border", "2", ""},
	"info":         {"", "", "info", "36", ""},
}

// kinds are the roles a screen asks Styled for, each the word whose colour it is.
var kinds = map[string]string{"accent": "working", "amber": "needs you"}

// roleOf is the role a word is drawn in: its own (roles), a state word's, or a kind's.
func roleOf(word string) string {
	if _, ok := roles[word]; ok {
		return word
	}
	if role, ok := kinds[word]; ok {
		word = role
	}
	return styles[word].colour
}

// colourOf is a word's colour in a theme.
func colourOf(word string, in theme) string { return roles[roleOf(word)][in] }

var backgroundRGB = regexp.MustCompile(`^rgba?:([0-9a-fA-F]+)/([0-9a-fA-F]+)/([0-9a-fA-F]+)`)

// backgroundOf is the colour an answer names, rrggbb, "" where it names none to tell, and whether
// its luma is past half way.
func backgroundOf(answer string) (rgb string, light bool) {
	found := backgroundRGB.FindStringSubmatch(answer)
	if found == nil {
		return "", false
	}
	var channel [3]float64
	for i, part := range found[1:] {
		value, err := strconv.ParseUint(part, 16, 64)
		if err != nil {
			return "", false
		}
		channel[i] = float64(value) / (math.Pow(16, float64(len(part))) - 1)
		rgb += fmt.Sprintf("%02x", int(math.RoundToEven(channel[i]*255)))
	}
	return rgb, 0.2126*channel[0]+0.7152*channel[1]+0.0722*channel[2] > 0.5
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
	own                  own // where the look reads on the terminal's own background (lookOn)
}

// For is out as a screen that never asks its terminal what it is: in the shades kept (kept).
func For(out io.Writer) Screen {
	return Screen{depth: depth(out, false), width: width(out), ascii: !utf8(), theme: kept()}
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
// where COLORTERM says so, rgb, a terminal's own features, does, or terminfo counts 256 or more, as
// a seat's tmux takes every terminal for (Python's terminal._depth); else eight where it counts eight.
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
		return 24
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
	if s.Moves() {
		code = s.ink(rgb, "38")
	}
	if (word == "dim" || word == "idle") && s.depth == 8 {
		code = "2"
	} else if look.emphasis != "" {
		code = look.emphasis + ";" + code
	}
	return "\x1b[" + code + "m" + text + "\x1b[0m"
}

// ink is rgb as the code that draws it above eight colours: the text's, or with ground 48 the
// background's.
func (Screen) ink(rgb, ground string) string {
	return ground + ";2;" + strings.Join(channels(rgb), ";")
}

func channels(rgb string) []string {
	var parts []string
	for i := 0; i < 6; i += 2 {
		value, _ := strconv.ParseUint(rgb[i:i+2], 16, 8)
		parts = append(parts, strconv.Itoa(int(value)))
	}
	return parts
}

// Glyph is a state word's mark alone.
func (s Screen) Glyph(word string) string {
	if s.ascii {
		return styles[word].ascii
	}
	return styles[word].glyph
}

// Unsent is `¶ <text>`, `* <text>` without UTF-8: what the owner left unsent (menu.unsent_mark),
// on the row, its open line and the seat's bar alike.
func (s Screen) Unsent(text string) string {
	if s.ascii {
		return "* " + text
	}
	return "¶ " + text
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
