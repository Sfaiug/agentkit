package menu

import (
	"strings"

	"agentkit/internal/terminal"
)

// A bar is a line of a barChart: its name, its share of a line full, in word's colour, and the
// cells after it.
type bar struct {
	name  string
	share float64
	word  string
	cells []string
}

// barChart is heading, then a line of each of bars, its share of a line full (ShareLine) taking the
// room the cells after it leave, each cell aligned right, folding under its name where shorter than
// a plan bar's ever is: Python's menu.bar_chart, drawn under a limit on `config · limits`.
func barChart(s terminal.Screen, heading string, bars []bar) []string {
	room, wide, widths := s.LayoutWidth(), 0, []int(nil)
	for _, each := range bars {
		wide = max(wide, terminal.Cells(each.name))
		widths = append(widths, make([]int, max(0, len(each.cells)-len(widths)))...)
		for n, cell := range each.cells {
			widths[n] = max(widths[n], terminal.Cells(cell))
		}
	}
	size := room - 4
	for _, width := range widths {
		size -= 2 + width
	}
	folded := size-wide < 8
	if !folded {
		size -= wide
	}
	lines := []string{""}
	for _, part := range terminal.Wrap(heading, room-2) {
		lines = append(lines, "  "+part)
	}
	for _, each := range bars {
		tail := s.ShareLine(each.share, max(1, size), each.word)
		for n, cell := range each.cells {
			tail += "  " + strings.Repeat(" ", widths[n]-terminal.Cells(cell)) + cell
		}
		tail = strings.TrimRight(tail, " ")
		if folded {
			lines = append(lines, "  "+each.name, "    "+tail)
		} else {
			lines = append(lines, "  "+terminal.Pad(each.name, wide)+"  "+tail)
		}
	}
	return lines
}
