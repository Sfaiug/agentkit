package menu

import (
	"cmp"
	"math"
	"slices"
	"strconv"
	"strings"

	"agentkit/internal/matrix"
	"agentkit/internal/quality"
	"agentkit/internal/terminal"
)

// The models screen's bars, the owner's design of 5 Nov 2026: the dearest barsTall cells high, a
// column barsWide cells wide and a name on barsNamed lines of it, each at most.
const barsTall, barsWide, barsNamed = 7, 12, 3

var (
	counts = [quality.Places + 1]string{"no", "one", "two", "three", "four", "five"}
	tops   = [8]string{"", "▁", "▂", "▃", "▄", "▅", "▆", "▇"} // a bar's top, by the eighths of a cell it fills
)

// barLines is text wrapped at its words onto barsNamed lines of room cells, a word longer than a
// line cut with `…`; where more would follow, the last line's whole words that leave it a cell.
func barLines(text string, room int) []string {
	words := strings.Fields(text)
	for n, word := range words {
		words[n] = terminal.Cut(word, room)
	}
	lines := terminal.Wrap(strings.Join(words, " "), room)
	if len(lines) <= barsNamed {
		return lines
	}
	return append(lines[:barsNamed-1], terminal.Wrap(lines[barsNamed-1], room-1)[0]+"…")
}

// modelsBars is Python's menu.models_bars: role's answer found drawn as bars under the role lines,
// used the row the role uses.  Under a heading counting them, its choices, then as many of its
// others, best first, as fill quality.Places; side by side, cheapest on the left, each as tall as
// its cost over the dearest shown, in eighths of a cell, its cost (costSaid) on its top and under
// it its quality, its name (barLines) and its effort.  A choice is solid, an other shaded, its why
// under it led by its shade, so one too short to show its shade still says it is one; used is in
// the accent colour, a line under its name.  No axis line: heights and costs say which is dearer,
// as a shaded bar on the right is dearer, not better.  On a narrow screen the two-cell gutters,
// then the indent, give way to the labels.
func modelsBars(s terminal.Screen, found *quality.Said, role string, used *quality.Rating) []string {
	solid, shade, mark := "█", "░", "━"
	if s.ASCII() {
		solid, shade, mark = "#", ":", "="
	}
	type standing struct {
		row  *quality.Rating
		fill string
		why  string // a shaded one's
	}
	var rows []standing
	for _, row := range found.Choices {
		rows = append(rows, standing{row: row, fill: solid})
	}
	shaded := found.Others[:min(len(found.Others), quality.Places-len(found.Choices))]
	for _, other := range shaded {
		rows = append(rows, standing{other.Rating, shade, other.Why})
	}
	slices.SortStableFunc(rows, func(a, b standing) int { return cmp.Compare(*a.row.Cost, *b.row.Cost) })
	width := s.LayoutWidth()
	size := max(1, min(barsWide, (width-2*len(rows))/max(1, len(rows))))
	labels := make([][3]string, len(rows)) // each one's cost, quality and effort
	widths, total := make([]int, len(rows)), 0
	for n, one := range rows {
		labels[n] = [3]string{costSaid(s, found, one.row), strconv.FormatFloat(one.row.Quality, 'f', 1, 64), one.row.Effort}
		widths[n] = max(size, terminal.Cells(labels[n][0]), terminal.Cells(labels[n][1]), terminal.Cells(labels[n][2]))
		total += widths[n]
	}
	gap := 1
	if total+2*len(rows) <= width {
		gap = 2
	}
	lead := max(0, min(2, width-total-gap*(len(rows)-1)))
	heading := []string{matrix.ConfigRoles[role], counts[len(found.Choices)] + " choice"}
	if len(found.Choices) != 1 {
		heading[1] += "s"
	}
	if len(shaded) > 0 {
		heading = append(heading, counts[len(shaded)]+" more shaded")
	}
	lines := []string{""}
	for _, line := range packed(heading, " · ", width-2) {
		lines = append(lines, "  "+line)
	}
	dearest := 0.0
	for _, one := range rows {
		dearest = max(dearest, *one.row.Cost)
	}
	if dearest == 0 {
		dearest = 1
	}
	// each bar's parts, which stand on the same lines as the others': its chart, quality, name,
	// effort and why
	columns := make([][5][]string, len(rows))
	stood := 0 // the eighths the bar on the left stands
	for n, one := range rows {
		// an eighth of a cell; a whole one without UTF-8, and on a shaded bar, as no glyph shades a
		// part of a cell: its top would stand solid on its shade
		step := 8
		if !s.ASCII() && one.fill == solid {
			step = 1
		}
		// and never under the cheaper bar on its left, which a whole shaded cell may overtake
		stood = max(step, step*int(math.RoundToEven(8*barsTall*(*one.row.Cost)/dearest/float64(step))), (stood+step-1)/step*step)
		top := (stood + 7) / 8
		var chart []string
		for level := barsTall + 1; level > 0; level-- {
			switch {
			case level == top+1:
				chart = append(chart, labels[n][0])
			case level > top:
				chart = append(chart, "")
			case stood >= 8*level:
				chart = append(chart, strings.Repeat(one.fill, size))
			default:
				chart = append(chart, strings.Repeat(tops[stood%8], size))
			}
		}
		name := barLines(one.row.Name, widths[n])
		if one.row == used {
			name = append(name, strings.Repeat(mark, size))
		}
		var why []string
		if one.fill == shade {
			why = barLines(shade+" "+one.why, widths[n])
		}
		columns[n] = [5][]string{chart, {labels[n][1]}, name, {labels[n][2]}, why}
	}
	for part := range 5 {
		deep := 0
		for _, column := range columns {
			deep = max(deep, len(column[part]))
		}
		for at := range deep {
			cells := make([]string, len(rows))
			for n, column := range columns {
				text := ""
				if at < len(column[part]) {
					text = column[part][at]
				}
				// spaced after its colour, so no line keeps trailing space
				spaces := strings.Repeat(" ", max(0, widths[n]-terminal.Cells(text)))
				if rows[n].row == used {
					text = s.Styled(text, "accent")
				}
				cells[n] = text + spaces
			}
			lines = append(lines, strings.TrimRight(strings.Repeat(" ", lead)+strings.Join(cells, strings.Repeat(" ", gap)), " "))
		}
	}
	return lines
}
