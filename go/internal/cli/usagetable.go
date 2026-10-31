package cli

import (
	"strings"

	"agentkit/internal/pick"
	"agentkit/internal/terminal"
	"agentkit/internal/usage"
)

// usageHeadings are the table's headings, and usageShort those it takes where they do not fit.
var (
	usageHeadings = []string{"provider", "model(s)", "left", "holds", "a month", "resets", "week elapsed", "session",
		"resets held", "headroom", "budget", "outlook"}
	usageShort = []string{"provider", "model(s)", "left", "holds", "month", "resets", "elapsed", "session", "held",
		"room", "budget", "outlook"}
)

// usageText is `ak usage` as Python's usage.render draws it: a row per subscription, under short
// headings where the full ones do not fit and as a phone's label and value pairs where the
// table still does not, its notes, the pick order and the review pair, each line wrapped to the
// terminal.
func usageText(screen terminal.Screen, readings *usage.Readings, rules *pick.Rules, order []string) string {
	width, rows := screen.Width(), readings.Rows()
	table := append([][]string{usageHeadings}, rows...)
	widths := usageWidths(table)
	if width >= 60 && !usageFits(widths, width) {
		table[0] = usageShort
		widths = usageWidths(table)
		// model(s), provider and outlook give way first
		widths[1], widths[0], widths[11] = min(widths[1], 14), min(widths[0], 12), min(widths[11], 18)
	}
	var lines []string
	if usageFits(widths, width) {
		for _, row := range table {
			cells := make([]string, len(row))
			for i, cell := range row {
				cell = terminal.Cut(cell, widths[i])
				cells[i] = cell + strings.Repeat(" ", widths[i]-terminal.Cells(cell))
			}
			lines = append(lines, strings.TrimRight(strings.Join(cells, " "), " "))
		}
		lines[0] = screen.Styled(lines[0], "dim")
	} else {
		// every meter still fits on a phone, nothing numeric dropped to squeeze a row
		labels := 0
		for _, heading := range usageHeadings[2:] {
			labels = max(labels, len(heading))
		}
		for _, row := range rows {
			if len(lines) > 0 {
				lines = append(lines, "")
			}
			for _, line := range terminal.Wrap(row[0]+" · "+row[1], width) {
				lines = append(lines, screen.Bold(line))
			}
			for i, value := range row[2:] {
				prefix := "  " + usageHeadings[i+2] + strings.Repeat(" ", labels-len(usageHeadings[i+2])) + "  "
				for _, part := range terminal.Wrap(value, width-len(prefix)) {
					lines = append(lines, prefix+part)
					prefix = strings.Repeat(" ", len(prefix))
				}
			}
		}
	}
	lines = append(lines, readings.Notes(func(text string) string { return screen.Styled(text, "dim") })...)
	picked := "(none: every worker's provider is exhausted)"
	if len(order) > 0 {
		picked = strings.Join(order, ", ")
	}
	lines = append(lines, "pick order: "+picked)
	if executor, reviewer, ok := rules.Pair(readings); ok {
		review := "review: " + executor + " by " + reviewer
		if rules.Same(executor, reviewer) {
			review += ", self-reviewed"
		}
		lines = append(lines, review)
	}
	var shown []string
	for _, line := range lines {
		if terminal.Cells(terminal.Plain(line)) <= width {
			shown = append(shown, line)
		} else {
			shown = append(shown, terminal.Wrap(line, width)...)
		}
	}
	return strings.Join(shown, "\n")
}

// usageWidths is each column's widest cell.
func usageWidths(table [][]string) []int {
	widths := make([]int, len(table[0]))
	for _, row := range table {
		for i, cell := range row {
			widths[i] = max(widths[i], terminal.Cells(cell))
		}
	}
	return widths
}

// usageFits is whether columns that wide fit the terminal a space apart.
func usageFits(widths []int, width int) bool {
	total := len(widths) - 1
	for _, each := range widths {
		total += each
	}
	return total <= width
}
