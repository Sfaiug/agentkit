// Package menu draws ak's screens.  This file is the models screen's answer per role, as `ak
// models` prints it and as the `r recommended` screen will: each role's line of best quality for
// the money, from its best, and the legend.
package menu

import (
	"slices"
	"strconv"
	"strings"
	"time"

	"agentkit/internal/quality"
	"agentkit/internal/terminal"
)

const (
	mark  = 7     // a row's mark's column, as wide as `r takes`
	named = 13    // the cells before a legend line's words: its name's column
	gap   = " · " // between two things said on one line
)

var (
	heads  = map[string]string{"orchestrate": "orch", "execute": "builds", "review": "reviews"}
	legend = [][2]string{{"left out", "a row no better than a cheaper one, yours compared with yours"}}
)

// A Line is one row of a role's answer, or the words Said where it says something else.
type Line struct {
	Said, Mark, Name, Word, Quality, Cost, Maker string
	Cells, Notes                                 []string
	Near                                         float64
}

// A Role is what the screen says of one role's answer: its head and full frontier.
type Role struct {
	Head  string
	Lines []Line
}

// ModelsSaid matches Python's models_said: each role's head and frontier, pick and take
// marked, quality full at the best and empty ten points behind.
func ModelsSaid(screen terminal.Screen, answer map[string]*quality.Said, lineup []quality.Row) []Role {
	levels := map[string][]string{} // each release's efforts on the boards, weakest first
	for _, row := range lineup {
		levels[row.Release] = append(levels[row.Release], row.Effort)
	}
	var said []Role
	for _, role := range quality.Roles {
		found := answer[role]
		var out Role
		for _, row := range found.Front {
			var notes []string
			if missing := row.Missing(); missing > 0 {
				notes = append(notes, screen.Styled(strconv.Itoa(missing)+" missing", "dim"))
			}
			if !row.Yours {
				notes = append(notes, screen.Styled("no harness", "dim"))
			}
			taken := levels[row.Release]
			line := Line{Name: row.Name, Word: row.Effort, Notes: notes, Maker: row.Maker,
				Cells:   screen.EffortCells(len(taken), slices.Index(taken, row.Effort)+1),
				Near:    max(0, 1-(*found.Best-row.Quality)/10),
				Quality: strconv.FormatFloat(row.Quality, 'f', 1, 64),
				Cost:    "$" + strconv.FormatFloat(*row.Cost, 'f', 2, 64)}
			switch row {
			case found.Pick:
				line.Mark = screen.Styled("★ pick", "working")
			case found.Take:
				line.Mark = "r takes"
			}
			out.Lines = append(out.Lines, line)
			if row == found.Pick && found.Take == nil {
				out.Lines = append(out.Lines, Line{Said: "no harness of yours runs a model this good"})
			}
		}
		// the first row is the best but where the best has no cost, so the head says it then
		out.Head = heads[role]
		if len(found.Front) == 0 {
			out.Head += gap + "none"
		} else if found.Front[0].Quality < *found.Best {
			out.Head += gap + "best " + strconv.FormatFloat(*found.Best, 'f', 1, 64)
		}
		said = append(said, out)
	}
	return said
}

// packed is parts on as few lines of room cells as hold them, separator between two on one line.
func packed(parts []string, room int) []string {
	var lines []string
	for _, part := range parts {
		if len(lines) > 0 && terminal.Cells(lines[len(lines)-1]+gap+part) <= room {
			lines[len(lines)-1] += gap + part
		} else {
			lines = append(lines, part)
		}
	}
	return lines
}

// modelsBody is the screen's lines.  Per role, a blank line between two, its head, beside the first
// with rows the columns' heads, then its lines: a row's mark in `mark` cells, its name, its effort
// -- its cells, then its word, in one column after the most cells any row has -- its line, taking
// the room the other columns leave, then its quality, cost and notes, these one under another in a
// column as wide as the widest. Every column fits the full frontier.
// Where that leaves the line under 8 cells, the notes' column gives
// way first, each row's notes going under it; where the line is still under 8 cells, each row's
// mark, then its name and effort, take a line and its line, numbers and notes the next, the name
// alone cut; the notes that do not fit beside the numbers then go under the row, broken only
// between two. Then the legend, how many of the total listed models of your companies are
// compared (matrix.Compared) and when the boards were read, broken only at ` · `.
func modelsBody(screen terminal.Screen, said []Role, compared map[string]bool, total int, fetched float64, light ModelLight) []matrixRow {
	room := screen.LayoutWidth()
	var rows []Line
	for _, role := range said {
		for _, line := range role.Lines {
			if line.Said == "" {
				rows = append(rows, line)
			}
		}
	}
	tall := 0
	for _, row := range rows {
		tall = max(tall, len(row.Cells))
	}
	effort := func(row Line) string {
		if row.Word == "" {
			return ""
		}
		if tall == 0 {
			return row.Word
		}
		return strings.Join(row.Cells, "") + strings.Repeat(" ", tall-len(row.Cells)+2) + row.Word
	}
	label, levelled, notesWide := 0, 0, 0
	qualityWide, costWide := terminal.Cells("quality"), terminal.Cells("a task")
	for _, row := range rows {
		label = max(label, terminal.Cells(row.Name))
		levelled = max(levelled, terminal.Cells(effort(row)))
		qualityWide = max(qualityWide, terminal.Cells(row.Quality))
		costWide = max(costWide, terminal.Cells(row.Cost))
		for _, note := range row.Notes {
			notesWide = max(notesWide, terminal.Cells(note))
		}
	}
	after := 2 + qualityWide + 2 + costWide + 2 + notesWide // the columns after the line
	before := 2 + mark + 2 + label + 2 + levelled + 2       // the cells before a row's line
	if room-before-after < 8 && 8 <= room-before-after+2+notesWide {
		after -= 2 + notesWide // notes are rare, so they go under their row before it folds
	}
	wide := room-before-after >= 8
	if !wide {
		before = 4 // folded, the line under the name
	}
	size := max(8, room-before-after)
	under := 6 // 2 cells in from a row's name
	if wide {
		under = 2 + mark + 2 + 2
	}
	first := slices.IndexFunc(said, func(role Role) bool { return len(role.Lines) > 0 })
	var lines []matrixRow
	at, next := -1, 0
	put := func(line string) { lines = append(lines, matrixRow{line: strings.TrimRight(line, " "), row: at}) }
	fill := func(text string, width int) string { return strings.Repeat(" ", max(0, width-terminal.Cells(text))) }
	for number, role := range said {
		at = -1
		if number > 0 {
			put("")
		}
		if number != first || !wide {
			put("  " + role.Head)
		}
		if number == first {
			head := ""
			if wide {
				head = role.Head
			}
			put("  " + terminal.Pad(head, before+size-2) + "  " +
				fill("quality", qualityWide) + screen.Styled("quality", "dim") + "  " +
				fill("a task", costWide) + screen.Styled("a task", "dim"))
		}
		for _, line := range role.Lines {
			if line.Said != "" { // the words under the pick, wrapped at words, are its row's
				for _, part := range terminal.Wrap(line.Said, room-under) {
					put(strings.Repeat(" ", under) + part)
				}
				continue
			}
			at, next = next, next+1
			text := effort(line)
			nameRoom := label
			if !wide {
				nameRoom = min(label, room-6-levelled)
			}
			name, ink := modelPaint(screen, line, terminal.Pad(line.Name, nameRoom), light)
			lead := name + "  " + text + fill(text, levelled) + "  "
			if wide {
				lead = "  " + line.Mark + fill(line.Mark, mark) + "  " + lead
			} else {
				if line.Mark != "" {
					put("    " + line.Mark)
				}
				put("    " + lead)
				lead = "    "
			}
			tail := lead + screen.ShareLine(line.Near, size, ink) + "  " +
				fill(line.Quality, qualityWide) + line.Quality + "  " + fill(line.Cost, costWide) + line.Cost + "  "
			fit := 0 // the notes that fit, the rest under
			for n := range len(line.Notes) + 1 {
				if terminal.Cells(tail+strings.Join(line.Notes[:n], gap)) <= room {
					fit = n
				}
			}
			put(tail + strings.Join(line.Notes[:fit], gap))
			column := terminal.Cells(tail) // the notes', one under another where it fits
			if column+notesWide > room {
				column = under
			}
			for _, part := range packed(line.Notes[fit:], room-column) {
				put(strings.Repeat(" ", column) + part)
			}
		}
	}
	at = -2 // the legend stays below the scrollable rows
	put("")
	for _, entry := range legend {
		for number, part := range terminal.Wrap(entry[1], room-named) {
			name := entry[0]
			if number > 0 {
				name = ""
			}
			put("  " + screen.TableRow([]string{name, part}, []int{9, room - named}, []string{"", "dim"}))
		}
	}
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
	for _, part := range packed(parts, room-2) {
		put("  " + screen.Styled(part, "dim"))
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
