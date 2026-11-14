// Package menu draws ak's screens.  This file is what `ak models` prints: the models screen's role
// lines, how many models are compared, and ak's own numbers.
package menu

import (
	"strconv"
	"strings"
	"time"

	"agentkit/internal/quality"
	"agentkit/internal/terminal"
)

const gap = " · " // between two things said on one line

// ModelsLines is what `ak models` prints of view, as Python's matrix.main does: the models screen's
// role lines, no role pointed at, then each role's bars in turn, then a blank line and how many
// models are compared.
func ModelsLines(s terminal.Screen, view ModelsView) []string {
	var lines []string
	for _, row := range roleLines(s, view, -1) {
		lines = append(lines, row.line)
	}
	for _, role := range quality.Roles {
		lines = append(lines, modelsBars(s, view.Answer[role], role, view.Uses[role].Row)...)
	}
	return append(append(lines, ""), modelsRead(s, view.Compared, view.Total, view.Fetched)...)
}

// packed is parts on as few lines of room cells as hold them, separator between two on one line; a
// part too long for a line of its own goes on at its words, never past room, where the terminal
// would break it mid-word.
func packed(parts []string, room int) []string {
	var lines []string
	for _, part := range parts {
		if len(lines) > 0 && terminal.Cells(lines[len(lines)-1]+gap+part) <= room {
			lines[len(lines)-1] += gap + part
		} else if terminal.Cells(part) > room {
			lines = append(lines, terminal.Wrap(part, room)...)
		} else {
			lines = append(lines, part)
		}
	}
	return lines
}

// modelsRead is how many of your companies' total listed models are compared (matrix.Compared),
// and when the boards were read, broken only at ` · `.
func modelsRead(screen terminal.Screen, compared map[string]bool, total int, fetched float64) []string {
	shown := "all"
	if len(compared) != total {
		shown = strconv.Itoa(len(compared)) + " of"
	}
	parts := []string{"comparing " + shown + " " + strconv.Itoa(total) + " models"}
	if fetched != 0 {
		read, now := time.Unix(0, int64(fetched*1e9)), time.Now()
		layout := "02 Jan 15:04"
		if read.Format(time.DateOnly) == now.Format(time.DateOnly) {
			layout = "15:04"
		}
		parts = append(parts, "boards read "+read.Format(layout))
	}
	var lines []string
	for _, part := range packed(parts, screen.LayoutWidth()-2) {
		lines = append(lines, "  "+screen.Styled(part, "dim"))
	}
	return lines
}

// LiveLines is the second table: each configured model's own numbers per role, `55% of 320`, rows
// holding its name and a cell per role.
func LiveLines(screen terminal.Screen, rows [][]string) []string {
	table := append([][]string{{"model", "orch", "exec", "review"}}, rows...)
	widths := make([]int, 4)
	for _, row := range table {
		for i, text := range row {
			widths[i] = max(widths[i], terminal.Cells(text))
		}
	}
	room := screen.LayoutWidth()
	drawn := make([]string, len(table))
	for n, row := range table {
		cells := make([]string, 4)
		for i, text := range row {
			cells[i] = terminal.Pad(text, widths[i])
		}
		drawn[n] = strings.TrimRight(strings.Join(cells, " "), " ")
	}
	// a row wider than the terminal wraps rather than run past its edge
	fit := func(text string) []string {
		if terminal.Cells(text) <= room {
			return []string{text}
		}
		return terminal.Wrap(text, room)
	}
	var lines []string
	head := terminal.Wrap("ak's own runs, never ranking: merged in round 1 of the runs it executed, let "+
		"through in round 1 of those it reviewed, merged in round 1 of its seat's own pull requests", room)
	for _, part := range append(head, fit(drawn[0])...) {
		lines = append(lines, screen.Styled(part, "dim"))
	}
	for _, line := range drawn[1:] {
		lines = append(lines, fit(line)...)
	}
	return lines
}
