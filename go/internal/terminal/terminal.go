// Package terminal handles presentation: widths, wrapping, fitted columns and the state words'
// glyphs and colours, and the keyboard of a screen that takes the terminal.  The one host tool it
// asks is tmux, for what the terminal of the client it runs under takes.
package terminal

import (
	"cmp"
	"encoding/hex"
	"io"
	"math"
	"os"
	"regexp"
	"slices"
	"strconv"
	"strings"
	"sync"
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

// roleOf is the role a word's colour is: its own (roles), a state word's, or a kind's.
func roleOf(word string) string {
	if _, ok := roles[word]; ok {
		return word
	}
	if role, ok := kinds[word]; ok {
		word = role
	}
	return styles[word].colour
}

// xtermPalette is xterm's 240 fixed colours, from 16 up: the 6x6x6 cube, then 24 greys.
var xtermPalette = func() [240][3]byte {
	var all [240][3]byte
	for n := range 216 {
		all[n] = [3]byte{byte(cube[n/36]), byte(cube[n/6%6]), byte(cube[n%6])}
	}
	for n := range 24 {
		grey := byte(8 + 10*n)
		all[216+n] = [3]byte{grey, grey, grey}
	}
	return all
}()

type drawnKey struct {
	shades  theme
	ground  string
	nearest bool
}

var (
	drawnMu    sync.RWMutex
	drawnCache = map[drawnKey]map[string]string{}
)

func luma(rgb [3]byte) int {
	return 2126*int(rgb[0]) + 7152*int(rgb[1]) + 722*int(rgb[2])
}

func rgbBytes(hexRGB string) [3]byte {
	raw, _ := hex.DecodeString(hexRGB)
	return [3]byte{raw[0], raw[1], raw[2]}
}

// drawn is {role: its colour} as a screen in shades draws it on a terminal whose own background is
// ground (the theme's where none was said), matching Python's terminal._drawn: each colour moves as
// the theme's background does to reach the terminal's, by the share of the way from the text to
// that background its lightness is; with nearest, each takes the nearest unused xterm-256 entry.
func drawn(shades theme, ground string, nearest bool) map[string]string {
	key := drawnKey{shades, ground, nearest}
	drawnMu.RLock()
	if cached, ok := drawnCache[key]; ok {
		drawnMu.RUnlock()
		return cached
	}
	drawnMu.RUnlock()

	back, text := rgbBytes(roles["background"][shades]), rgbBytes(roles["text"][shades])
	to := back
	if ground != "" {
		to = rgbBytes(ground)
	}
	whole := luma(text) - luma(back)
	share := func(role string) int { return luma(text) - luma(rgbBytes(roles[role][shades])) }
	order := make([]string, 0, len(roles))
	for role := range roles {
		order = append(order, role)
	}
	slices.SortFunc(order, func(a, b string) int {
		if (a != "background") != (b != "background") {
			if a == "background" {
				return -1
			}
			return 1
		}
		if c := cmp.Compare(abs(share(a)), abs(share(b))); c != 0 {
			return c
		}
		return cmp.Compare(a, b)
	})
	used := make(map[[3]byte]bool, len(roles))
	out := make(map[string]string, len(roles))
	for _, role := range order {
		own, s := rgbBytes(roles[role][shades]), share(role)
		var rgb [3]byte
		for i := range 3 {
			v := int(own[i]) + int(math.RoundToEven(float64(int(to[i])-int(back[i]))*float64(s)/float64(whole)))
			rgb[i] = byte(min(255, max(0, v)))
		}
		if nearest {
			best, bestDist := xtermPalette[0], math.MaxInt
			for _, entry := range xtermPalette {
				if used[entry] {
					continue
				}
				d := 0
				for i := range 3 {
					diff := int(rgb[i]) - int(entry[i])
					d += diff * diff
				}
				if d < bestDist {
					best, bestDist = entry, d
				}
			}
			rgb = best
		}
		used[rgb] = true
		out[role] = hex.EncodeToString(rgb[:])
	}

	drawnMu.Lock()
	if len(drawnCache) >= 8 {
		clear(drawnCache)
	}
	drawnCache[key] = out
	drawnMu.Unlock()
	return out
}

// colour is a word's colour on this screen, its role's in the screen's theme, as Python's
// terminal.colour says it: the colour it has on the terminal's own background (drawn).
func (s Screen) colour(word string) string {
	return drawn(s.theme, s.ground, s.depth == 256)[roleOf(word)]
}

var backgroundRGB = regexp.MustCompile(`^rgba?:([0-9a-fA-F]+)/([0-9a-fA-F]+)/([0-9a-fA-F]+)`)

// background is the colour an answer names, `rrggbb`, "" where it names none to tell, and whether
// its luma is past half way.
func background(answer string) (rgb string, light bool) {
	found := backgroundRGB.FindStringSubmatch(answer)
	if found == nil {
		return "", false
	}
	var channel [3]float64
	said := make([]byte, 3)
	for i, part := range found[1:] {
		value, err := strconv.ParseUint(part, 16, 64)
		if err != nil {
			return "", false
		}
		channel[i] = float64(value) / (math.Pow(16, float64(len(part))) - 1)
		said[i] = byte(math.RoundToEven(255 * channel[i]))
	}
	return hex.EncodeToString(said), 0.2126*channel[0]+0.7152*channel[1]+0.0722*channel[2] > 0.5
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
	// The background its terminal said it has, `rrggbb`, which the screen sits on (colour); ""
	// where the terminal gave no answer.
	ground string
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

// ink is rgb as the code that draws it nearest above eight colours: the text's, or with ground 48
// the background's.
func (s Screen) ink(rgb, ground string) string {
	if s.depth == 24 {
		return ground + ";2;" + strings.Join(channels(rgb), ";")
	}
	return ground + ";5;" + strconv.Itoa(xterm(rgb))
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
