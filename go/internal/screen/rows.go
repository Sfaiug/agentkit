package screen

import (
	"regexp"
	"strconv"
	"strings"
	"unicode/utf8"

	"agentkit/internal/config"
)

// A capture holds its attributes (`capture-pane -e`): faint text is a suggestion, never typed.
var (
	sgrAll = regexp.MustCompile(`\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b\[[0-9;?]*[ -/]*[@-~]`)
	sgrSeq = regexp.MustCompile(`\x1b\[([0-9;]*)m`)
)

func strip(text string) string { return sgrAll.ReplaceAllString(text, "") }

// Plain is a row as read: no attributes, and stripped as Python's Unicode strip does, which is
// what takes the U+00A0 off an empty composer's row.
func Plain(line string) string { return strings.TrimFunc(strip(line), config.Space) }

// contentRows are the non-blank rows of a capture, right-stripped.  A blank row can still change
// an attribute, and tmux carries one on until something ends it, so its codes go on at the head
// of the next row (watch._content_rows).
func contentRows(text string) []string {
	var rows []string
	carried := ""
	for _, line := range config.SplitLines(text) {
		if Plain(line) != "" {
			rows = append(rows, carried+strings.TrimRightFunc(line, config.Space))
			carried = ""
			continue
		}
		for _, found := range sgrSeq.FindAllString(line, -1) {
			carried += found
		}
	}
	return rows
}

func plains(raws []string) []string {
	lines := make([]string, len(raws))
	for at, raw := range raws {
		lines[at] = Plain(raw)
	}
	return lines
}

// Said are the tail's rows without the chrome known to lie at its bottom: anything else below an
// old error means the seat has moved on (watch.content_lines).
func (r *Rules) Said(tail string) []string {
	var rows, lines []string
	for _, line := range config.SplitLines(tail) {
		if plain := Plain(line); plain != "" {
			rows, lines = append(rows, line), append(lines, plain)
		}
	}
	lines = lines[:r.chromeBelow(rows)]
	for len(lines) > 0 && r.chromeLine(lines[len(lines)-1]) {
		lines = lines[:len(lines)-1]
	}
	return lines
}

// chromeBelow is where a ruled composer begins in the rows, else their end: from its prompt row
// down to a footer on the bottom row nothing is output.  A bottom row that is no footer is newer
// output, and leaves the rows as they are.
func (r *Rules) chromeBelow(rows []string) int {
	at, end := r.ruledComposer(rows)
	last := ""
	for _, row := range rows {
		if strings.TrimFunc(row, config.Space) != "" {
			last = row
		}
	}
	if end >= 0 && r.chromeLine(last) {
		return at
	}
	return len(rows)
}

// LastInColour is whether the row at that place of the tail reads as `last` when only what it
// draws in a colour of its own is kept, and whether the pane holds attributes to tell by: a
// harness that draws its notices in colour and the answer in the terminal's own says a stall word
// only there (watch.stalled_on).
func LastInColour(pane string, place int, last string) (whole, attributes bool) {
	if !sgrSeq.MatchString(pane) {
		return false, false
	}
	var drawn []string
	colour := false
	for _, line := range config.SplitLines(pane) {
		shown := colourOf(line, &colour)
		if Plain(line) != "" {
			drawn = append(drawn, config.Fold(shown))
		}
	}
	drawn = lastOf(drawn, tailRows)
	return place < len(drawn) && drawn[place] == config.Fold(last), true
}

// colourOf is the line with only what it draws in a colour, the rest blank: tmux draws a colour
// once and carries it on to the lines under it until something ends it (watch.in_colour).
func colourOf(line string, colour *bool) string {
	var shown strings.Builder
	at := 0
	text := func(part string) {
		part = strip(part)
		if *colour {
			shown.WriteString(part)
		} else {
			shown.WriteString(strings.Repeat(" ", utf8.RuneCountInString(part)))
		}
	}
	for _, found := range sgrSeq.FindAllStringSubmatchIndex(line, -1) {
		text(line[at:found[0]])
		at = found[1]
		params := strings.Split(line[found[2]:found[3]], ";")
		for each := 0; each < len(params); {
			code, _ := strconv.Atoi(params[each])
			switch {
			case code == 0 || code == 39:
				*colour = false
			case code >= 30 && code <= 38 || code >= 90 && code <= 97:
				*colour = true
			}
			step := 1
			if (code == 38 || code == 48) && each+1 < len(params) {
				// `38;5;n`, `38;2;r;g;b` and their background twins name a colour in their run
				switch params[each+1] {
				case "5":
					step = 3
				case "2":
					step = 5
				}
			}
			each += step
		}
	}
	text(line[at:])
	return shown.String()
}
