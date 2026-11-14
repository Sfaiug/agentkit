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
// column barsWide cells wide, each at most.
const barsTall, barsWide = 7, 12

var (
	counts = [quality.Places + 1]string{"no", "one", "two", "three", "four", "five"}
	tops   = [8]string{"", "▁", "▂", "▃", "▄", "▅", "▆", "▇"} // a bar's top, by the eighths of a cell it fills
)

// Carried is false where a role's bars would hold a row only Python's answer gives a why: the row
// the role uses, priced and no choice, where it is none of the role's others (the best row of a
// release with no choice), which Python's bars draw first of the shaded ones.
func (view ModelsView) Carried() bool {
	for _, role := range quality.Roles {
		found, row := view.Answer[role], view.Uses[role].Row
		if row == nil || row.Cost == nil || view.Compared != nil && !view.Compared[row.Release] ||
			slices.Contains(found.Choices, row) {
			continue
		}
		if !slices.ContainsFunc(found.Others, func(other quality.Other) bool { return other.Rating == row }) {
			return false
		}
	}
	return true
}

// modelsBars is Python's menu.models_bars: role's answer found drawn as bars under the role lines,
// used the row the role uses.  Under a heading counting them, its choices, then its others, used
// first where it is one, as many as fill quality.Places; side by side, cheapest on the left, on a
// tie the worse, each as tall as its cost over the dearest shown, in eighths of a cell, its cost
// (costSaid) on its top and under it its quality, its name (columned) and its effort.  A choice is
// solid, the rest shaded, each one's why under it led by its shade, so one too short to show its
// shade still says it is one; used is in the accent colour, a line under its name.  No axis line:
// heights and costs say which is dearer, as a shaded bar on the right is dearer, not better.  On a
// narrow screen the two-cell gutters, then the indent, give way to the labels, and where a word too
// wide for its column widens it past the screen, fewer bars stand: the shaded ones go first, used
// last, then the cheapest choices, as the answer keeps the costliest.
func modelsBars(s terminal.Screen, found *quality.Said, role string, used *quality.Rating) []string {
	solid, shade, mark := "█", "░", "━"
	if s.ASCII() {
		solid, shade, mark = "#", ":", "="
	}
	width, choices, own := s.LayoutWidth(), found.Choices, 0
	var shaded []quality.Other
	for _, other := range found.Others {
		if other.Rating == used {
			shaded, own = append([]quality.Other{other}, shaded...), 1
		} else {
			shaded = append(shaded, other)
		}
	}
	shaded = shaded[:min(len(shaded), max(own, quality.Places-len(choices)))]
	type standing struct {
		row                   *quality.Rating
		fill                  string
		cost, quality, effort string
		words                 []string // its name, and a shaded one's why
	}
	var rows []standing
	var size, total int
	var widths []int
	for {
		rows = nil
		for _, row := range choices {
			rows = append(rows, standing{row: row, fill: solid, words: []string{row.Name}})
		}
		for _, other := range shaded {
			rows = append(rows, standing{row: other.Rating, fill: shade, words: []string{other.Name, shade + " " + other.Why}})
		}
		slices.SortStableFunc(rows, func(a, b standing) int {
			return cmp.Or(cmp.Compare(*a.row.Cost, *b.row.Cost), cmp.Compare(a.row.Quality, b.row.Quality))
		})
		size = max(1, min(barsWide, (width-2*len(rows))/max(1, len(rows))))
		widths, total = nil, 0
		for n := range rows {
			one := &rows[n]
			one.cost, one.quality, one.effort = costSaid(s, found, one.row), strconv.FormatFloat(one.row.Quality, 'f', 1, 64), one.row.Effort
			// a column as wide as its labels and its words' widest part (columned)
			wide := max(size, terminal.Cells(one.cost), terminal.Cells(one.quality), terminal.Cells(one.effort))
			for _, text := range one.words {
				for _, line := range columned(text, size, " -.") {
					wide = max(wide, terminal.Cells(line))
				}
			}
			widths, total = append(widths, wide), total+wide
		}
		if total+len(rows)-1 <= width { // one-cell gutters and no indent hold them
			break
		}
		if len(shaded) > 0 {
			shaded = shaded[:len(shaded)-1]
		} else {
			choices = choices[1:]
		}
	}
	gap := 1
	if total+2*len(rows) <= width {
		gap = 2
	}
	lead := max(0, min(2, width-total-gap*(len(rows)-1)))
	heading := []string{matrix.ConfigRoles[role], counts[len(choices)] + " choice"}
	if len(choices) != 1 {
		heading[1] += "s"
	}
	if len(shaded) > 0 {
		heading = append(heading, counts[len(shaded)]+" more shaded")
	}
	lines := []string{""}
	for _, line := range packed(heading, width-2) {
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
	columns := make([][][]string, len(rows))
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
				chart = append(chart, one.cost)
			case level > top:
				chart = append(chart, "")
			case stood >= 8*level:
				chart = append(chart, strings.Repeat(one.fill, size))
			default:
				chart = append(chart, strings.Repeat(tops[stood%8], size))
			}
		}
		name := columned(one.words[0], widths[n], " -.")
		if one.row == used {
			name = append(name, strings.Repeat(mark, size))
		}
		var why []string
		for _, text := range one.words[1:] {
			why = append(why, columned(text, widths[n], " -.")...)
		}
		columns[n] = [][]string{chart, {one.quality}, name, {one.effort}, why}
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
