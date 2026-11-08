package menu

import (
	"strconv"
	"strings"
	"time"

	"agentkit/internal/config"
	"agentkit/internal/matrix"
	"agentkit/internal/quality"
	"agentkit/internal/terminal"
)

const (
	unboarded = "not on the boards" // a model no row is
	unmarked  = "none"              // a role marking no model
)

// ModelsView is what the models screen, `r recommended` on `c`, draws: what each role Uses off
// its Answer (matrix.Uses), Models naming a model on no row; how many of Total models are
// Compared, and when the boards were Fetched; `▸` on the role At, by its place in quality.Roles,
// unless the pointer is Away; Top the first line shown and Note what is said under the rest.
type ModelsView struct {
	Title    string
	Answer   map[string]*quality.Said
	Uses     map[string]matrix.Use
	Models   map[string]config.Model
	Compared map[string]bool
	Total    int
	Fetched  float64
	At, Top  int
	Away     bool
	Note     string
}

// ModelsFrame is the models screen as Python's models_screen draws it: the role lines
// (roleLines) over how many models are compared, paged so the role At is shown.
func ModelsFrame(s terminal.Screen, view ModelsView) MatrixFrame {
	keys := "↑↓ role   ⏎ why   p models   r take   esc back"
	if s.ASCII() {
		keys = "up/down role   enter why   p models   r take   esc back"
	}
	at := view.At
	if view.Away {
		at = -1
	}
	body := roleLines(s, view, at)
	under := append([]string{""}, modelsRead(s, view.Compared, view.Total, view.Fetched)...)
	if view.Note != "" {
		under = append(under, "")
	}
	for _, part := range terminal.Wrap(view.Note, s.LayoutWidth()-2) {
		under = append(under, "  "+s.Styled(part, "dim"))
	}
	room := max(1, s.Height()-3-len(keyLine(s, keys, s.Width(), ""))-len(under))
	first, last := -1, -1
	for i, row := range body {
		if row.row == view.At {
			if first < 0 {
				first = i
			}
			last = i
		}
	}
	top := max(0, min(max(view.Top, min(last, first+room-1)-room+1), max(0, first), max(0, len(body)-room)))
	var lines []string
	spots := []matrixRow{{row: -1}, {row: -1}}
	for _, row := range body[top:min(top+room, len(body))] {
		lines, spots = append(lines, row.line), append(spots, row)
	}
	return MatrixFrame{Panel(s, view.Title, time.Now().Format("15:04"), append(lines, under...), keys), top, spots}
}

// RoleStep is the role ↑/↓ and the wheel move `▸` to, by roles on from at, held at the first and
// the last.
func RoleStep(at, by int) int {
	return min(max(at+by, 0), len(quality.Roles)-1)
}

// A roleSaid is one role's line as Python's models_said has it: the name and effort of the row it
// uses, then that row's quality and cost (numbered); else its model's, at the effort it runs it at,
// and after them `not on the boards`; else `none`.  Unit is its cost's.
type roleSaid struct {
	name, effort, quality, cost, after, unit string
	numbered                                 bool
}

func rolesSaid(s terminal.Screen, view ModelsView) []roleSaid {
	// a cost no run measured never looks more certain than it is: the owner, 3 Nov 2026
	about := "≈"
	if s.ASCII() {
		about = "~"
	}
	var said []roleSaid
	for _, role := range quality.Roles {
		found, use := view.Answer[role], view.Uses[role]
		one := roleSaid{name: unmarked, unit: units[found.CostUnit]}
		switch row := use.Row; {
		case row != nil:
			one.name, one.effort, one.numbered = row.Name, row.Effort, true
			one.quality, one.cost = strconv.FormatFloat(row.Quality, 'f', 1, 64), "-"
			if row.Cost != nil {
				one.cost = found.CostText(row)
				if row.CostRule != "measured" {
					one.cost = about + one.cost
				}
			}
		case use.Model != "":
			one.name, one.after = config.ModelName(use.Model, view.Models), unboarded
			if use.Effort != "none" {
				one.effort = use.Effort
			}
		}
		said = append(said, one)
	}
	return said
}

// roleLines is Python's models_body: per role `▸` where it is at (-1 for none), its word, the row it
// uses and what follows, under `quality` and its unit wherever the unit changes; a row too wide
// beside the words goes under its word, only its name cut.  Each line's row is its role's place in
// quality.Roles, -1 on a heading.
func roleLines(s terminal.Screen, view ModelsView, at int) []matrixRow {
	said := rolesSaid(s, view)
	room := s.LayoutWidth()
	mark := "▸"
	if s.ASCII() {
		mark = ">"
	}
	word, qualityWide, costWide := 0, terminal.Cells("quality"), 0
	for i, one := range said {
		word = max(word, terminal.Cells(matrix.ConfigRoles[quality.Roles[i]]))
		costWide = max(costWide, terminal.Cells(one.unit))
		if one.numbered {
			qualityWide, costWide = max(qualityWide, terminal.Cells(one.quality)), max(costWide, terminal.Cells(one.cost))
		}
	}
	right := func(text string, width int) string {
		return strings.Repeat(" ", max(0, width-terminal.Cells(text))) + text
	}
	follows := func(one roleSaid) string {
		switch {
		case one.numbered:
			return "  " + right(one.quality, qualityWide) + "  " + right(one.cost, costWide)
		case one.after != "":
			return "  " + s.Styled(one.after, "dim")
		}
		return ""
	}
	full, tail := 0, 0
	for _, one := range said {
		full, tail = max(full, terminal.Cells(withEffort(one.name, one.effort, room))), max(tail, terminal.Cells(follows(one)))
	}
	wide := 2+2+word+2+full+tail <= room
	before := 4 // folded, the row under its role's word
	if wide {
		before = 2 + 2 + word + 2
	}
	size := min(full, room-before-tail) // the rows' column, only a name cut to fit it
	var lines []matrixRow
	unit := ""
	for i, one := range said {
		if one.numbered && one.unit != unit { // a role with no numbers heads nothing
			unit = one.unit
			lines = append(lines, matrixRow{line: strings.Repeat(" ", max(0, before+size+2)) +
				s.Styled(right("quality", qualityWide)+"  "+right(unit, costWide), "dim"), row: -1})
		}
		pointer := " "
		if i == at {
			pointer = s.Styled(mark, "accent")
		}
		lead := "  " + pointer + " " + terminal.Pad(matrix.ConfigRoles[quality.Roles[i]], word) + "  "
		if !wide {
			lines = append(lines, matrixRow{line: strings.TrimRight(lead, " "), row: i})
			lead = strings.Repeat(" ", before)
		}
		used := terminal.Pad(withEffort(one.name, one.effort, size), size)
		lines = append(lines, matrixRow{line: strings.TrimRight(lead+used+follows(one), " "), row: i})
	}
	return lines
}

// withEffort is a model and its effort in room cells, only the name cut.
func withEffort(name, effort string, room int) string {
	if effort != "" {
		effort = " " + effort
	}
	return terminal.Cut(name, room-terminal.Cells(effort)) + effort
}
