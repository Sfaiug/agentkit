package menu

import (
	"slices"
	"strings"

	"agentkit/internal/config"
	"agentkit/internal/matrix"
	"agentkit/internal/quality"
	"agentkit/internal/terminal"
)

// RoleHead is the same role name on the config matrix and the models screen.
func RoleHead(role int) string { return heads[quality.Roles[role]] }

type ConfigOption struct{ Name, Value string }

type ConfigView struct {
	Matrix                      *matrix.Configuration
	Row, Column, Top            int
	Scope, Clock, Version, Note string
	Fresh                       bool
	Away                        bool // the pointer is on nothing drawn: no row or cell lit, the keys going on from Row
	Cells                       []Cell
	Options                     []ConfigOption
}

type matrixCell struct{ first, last, column int }
type matrixRow struct {
	line  string
	row   int
	cells []matrixCell
}

// MatrixFrame keeps the visible page and its cells together for keyboard and pointer input.
type MatrixFrame struct {
	Lines []string
	Top   int
	spots []matrixRow
}

// Hit is the row and cell the pointer is on where they are drawn (terminal.Under), column -1 on the
// row off its cells; not ok on nothing.
func (f MatrixFrame) Hit(mouse terminal.Mouse) (row, column int, ok bool) {
	if mouse.Row <= 0 || mouse.Row > min(len(f.spots), len(f.Lines)) || f.spots[mouse.Row-1].row < 0 {
		return 0, 0, false
	}
	spot := f.spots[mouse.Row-1]
	cells := make([][2]int, len(spot.cells))
	for i, cell := range spot.cells {
		cells[i] = [2]int{cell.first, cell.last}
	}
	switch at, on := terminal.Under(f.Lines[mouse.Row-1], mouse.Column, cells...); {
	case !on:
		return 0, 0, false
	case at < 0:
		return spot.row, -1, true
	default:
		return spot.row, spot.cells[at].column, true
	}
}

// ConfigFrame pages the matrix under the usage and above its version and key line.
func ConfigFrame(s terminal.Screen, view ConfigView) MatrixFrame {
	keys := "↑↓←→ move   "
	if s.ASCII() {
		keys = "arrows move   "
	}
	switch {
	case view.Row >= len(view.Matrix.Names):
		keys += "⏎ open   "
	case view.Column < 3:
		keys += "␣ mark   "
	default:
		keys += "␣ step   "
	}
	if s.ASCII() {
		keys = strings.NewReplacer("⏎", "enter", "␣", "space").Replace(keys)
	}
	keys += "r recommended   "
	if view.Fresh {
		keys += "a apply to all sessions   "
	}
	keys += "esc back"
	lit := view
	if view.Away {
		lit.Row = -1
	}
	body := configBody(s, lit)
	over := usageLines(s, view.Cells, s.LayoutWidth())
	if len(over) == 0 {
		over = usageSummary(view.Cells, s.LayoutWidth(), -1)
	}
	over = append(over, "")
	under := []string{"", "  " + s.Styled("Version "+view.Version, "dim")}
	for _, line := range terminal.Wrap(view.Note, s.LayoutWidth()-2) {
		under = append(under, "  "+s.Styled(line, "dim"))
	}
	room := max(1, s.Height()-5-len(keyLine(s, keys, s.Width(), ""))-len(under)-len(over))
	if room < least {
		for i := len(over) - 1; i >= 0; i-- {
			body = append([]matrixRow{{line: over[i], row: -1}}, body...)
		}
		room += len(over)
		over = nil
	}
	first, last := -1, -1
	for i, line := range body {
		if line.row == view.Row {
			if first < 0 {
				first = i
			}
			last = i
		}
	}
	if last-first+1 > room {
		for i, line := range body {
			if line.row == view.Row && slices.ContainsFunc(line.cells, func(cell matrixCell) bool { return cell.column == view.Column }) {
				first, last = i, i
				break
			}
		}
	}
	top := max(0, min(max(view.Top, last-room+1), max(0, first), max(0, len(body)-room)))
	lines := slices.Clone(over)
	spots := make([]matrixRow, 2+len(over))
	for i := range spots {
		spots[i].row = -1
	}
	for _, row := range body[top:min(top+room, len(body))] {
		lines = append(lines, row.line)
		spots = append(spots, row)
	}
	lines = append(lines, under...)
	return MatrixFrame{Panel(s, "config", view.Clock, lines, keys), top, spots}
}

// configBody sizes every role once per draw. Bars give way before words; on a phone
// the roles fold under their model, and the selected cell stays on the visible page.
func configBody(s terminal.Screen, view ConfigView) []matrixRow {
	c, room := view.Matrix, s.LayoutWidth()
	label, tall, headWidth := 1, 0, 0
	words := map[[2]int]string{}
	for _, name := range c.Names {
		label = max(label, terminal.Cells(config.ModelName(name, c.Models)))
		for _, col := range c.Columns(name) {
			if col >= 3 {
				tall = max(tall, len(s.EffortCells(len(c.Levels[name]), 0)))
			}
		}
	}
	widths := func(tall int) [6]int {
		var width [6]int
		for role := range quality.Roles {
			head := RoleHead(role)
			headWidth = max(headWidth, terminal.Cells(head))
			width[role] = 3
			if tall > 0 {
				width[role] = 4
			}
			width[role+3] = max(0, terminal.Cells(head)-width[role])
			for i, name := range c.Names {
				effort := c.Effort(name, role)
				words[[2]int{i, role}] = effort
				if !c.Marks(name)[role] {
					continue
				}
				wide := terminal.Cells(effort)
				if tall > 0 {
					for _, level := range c.Levels[name] {
						wide = max(wide, terminal.Cells(level))
					}
					wide += tall + 2
				}
				width[role+3] = max(width[role+3], wide)
			}
		}
		return width
	}
	width := widths(tall)
	total := func() int { return 6 + width[0] + width[1] + width[2] + width[3] + width[4] + width[5] }
	if 2+label+total() > room {
		tall, width = 0, widths(0)
	}
	folded := 3+total() > room
	headWidth = max(1, min(headWidth, room-6-max(width[0]+width[3], width[1]+width[4], width[2]+width[5])))
	if !folded {
		label = min(label, max(1, room-2-total()))
	} else {
		label = min(label, max(1, room-2))
	}
	var lines []matrixRow
	put := func(text string, row int, cells []matrixCell) {
		lines = append(lines, matrixRow{strings.TrimRight(text, " "), row, cells})
	}
	put("  "+s.Styled("For  ", "dim")+s.Bold(terminal.Cut(view.Scope, max(1, room-7))), -1, nil)
	if !folded {
		head := strings.Repeat(" ", 2+label)
		for role := range quality.Roles {
			head += "  " + terminal.Pad(RoleHead(role), width[role]+width[role+3])
		}
		put(s.Styled(strings.TrimRight(head, " "), "dim"), -1, nil)
	}
	harness := ""
	for i, name := range c.Names {
		if entry := c.Models[name]; entry.Harness != harness {
			harness = entry.Harness
			head, colour := config.HarnessLook(harness)
			put(s.Styled(head, colour), -1, nil)
		}
		line := "  " + terminal.Pad(config.ModelName(name, c.Models), label)
		cells := []matrixCell{{3, 2 + label, -1}}
		marks := c.Marks(name)
		for role := range quality.Roles {
			if folded {
				if role == 0 && i == view.Row {
					line = s.Highlight(line, true)
				}
				put(line, i, cells)
				line, cells = "    "+s.Styled(terminal.Pad(RoleHead(role), headWidth), "dim"), nil
			}
			line += "  "
			first := terminal.Cells(line) + 1
			glyph := "□"
			if marks[role] {
				glyph = "■"
			}
			if role == 0 {
				glyph = "○"
				if marks[role] {
					glyph = "●"
				}
			}
			if s.ASCII() {
				glyph = strings.NewReplacer("●", "*", "○", ".", "■", "x", "□", ".").Replace(glyph)
			}
			kind := ""
			if !marks[role] || role == 1 && len(c.Selected.List("workers")) == 0 {
				kind = "dim"
			}
			line += s.Toggle(glyph, width[role], i == view.Row && role == view.Column, kind)
			cells = append(cells, matrixCell{first, first + width[role] - 1, role})
			first += width[role]
			effort := ""
			if marks[role] {
				effort = words[[2]int{i, role}]
				word := effort
				if i == view.Row && role+3 == view.Column {
					word = s.Reverse(word)
				}
				if tall > 0 {
					bar := s.EffortCells(len(c.Levels[name]), slices.Index(c.Levels[name], effort)+1)
					word = strings.Join(bar, "") + strings.Repeat(" ", tall+2-len(bar)) + word
				}
				effort = word
				cells = append(cells, matrixCell{first, first + terminal.Cells(effort) - 1, role + 3})
			}
			line += effort + strings.Repeat(" ", max(0, width[role+3]-terminal.Cells(effort)))
		}
		if !folded && i == view.Row {
			line = s.Highlight(line, true)
		}
		put(line, i, cells)
	}
	put("", -1, nil)
	optionWidth := 0
	for _, option := range view.Options {
		if option.Value != "" {
			optionWidth = max(optionWidth, terminal.Cells(option.Name))
		}
	}
	valueWidth := max(1, room-4-optionWidth)
	for i, option := range view.Options {
		parts := terminal.Wrap(option.Value, valueWidth)
		if len(parts) == 0 {
			parts = []string{""}
		}
		for number, part := range parts {
			name := ""
			if number == 0 {
				name = option.Name
			}
			line := "  " + s.TableRow([]string{name, part}, []int{optionWidth, valueWidth}, nil)
			if option.Value == "" {
				line = "  " + terminal.Cut(name, room-2)
			}
			if view.Row == len(c.Names)+i {
				line = s.Highlight(line, number == 0)
			}
			put(line, len(c.Names)+i, nil)
		}
	}
	return lines
}
