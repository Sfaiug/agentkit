package menu

import (
	"slices"
	"strconv"
	"strings"
	"time"

	"agentkit/internal/matrix"
	"agentkit/internal/terminal"
)

// A CompanyListView is what the company list (menu.company_list) is drawn from: each company
// with a listed model and yours (matrix.Companies), the releases on (matrix.Compared), the row of
// Shown the keys are on, `+ add a company` after the last, and its cell, 0 the name; the first
// line of the page; whether the pointer left every row, which draws none lit; and what to say
// under the count, why a change was not saved.
type CompanyListView struct {
	Title, Note      string
	Listed           []matrix.Company
	Yours            []string
	On               map[string]bool
	Row, Column, Top int
	Away             bool
}

// Shown is each of yours with a listed model, in your order: a row each.
func (view CompanyListView) Shown() []matrix.Company {
	var shown []matrix.Company
	for _, maker := range view.Yours {
		if at := slices.IndexFunc(view.Listed, func(one matrix.Company) bool { return one.Maker == maker }); at >= 0 {
			shown = append(shown, view.Listed[at])
		}
	}
	return shown
}

// CompanyListFrame is `<title> · models`: what on means over your companies (companiesBody), paged
// so the row the keys are on is shown, or of a row taller than the page its cell, and under them,
// dim, how many models are on, from how many companies, and how many more have benchmark scores,
// then the Note.
func CompanyListFrame(s terminal.Screen, view CompanyListView) MatrixFrame {
	keys := "↑↓←→ move   ␣ mark   a add a company   esc back"
	if s.ASCII() {
		keys = "arrows move   space mark   a add a company   esc back"
	}
	room, shown := s.LayoutWidth(), view.Shown()
	var over []string
	for _, part := range terminal.Wrap("ak uses only the models that are on. Space marks one on or off, or, on "+
		"a company's name, all of them. A company with none on leaves the list.", room-2) {
		over = append(over, "  "+part)
	}
	over = append(over, "")
	lit := view.Row
	if view.Away {
		lit = -1
	}
	body := companiesBody(s, shown, view.On, lit, view.Column)
	giving := 0
	for _, company := range shown {
		if slices.ContainsFunc(company.Models, func(model [2]string) bool { return view.On[model[0]] }) {
			giving++
		}
	}
	more := len(view.Listed) - len(shown)
	said := []string{counted(len(view.On), "model", "models") + " on, from " + counted(giving, "company", "companies"),
		counted(more, "more company has", "more companies have") + " benchmark scores"}
	under := []string{""}
	for _, part := range packed(said, room-2) {
		under = append(under, "  "+s.Styled(part, "dim"))
	}
	if view.Note != "" {
		under = append(under, "")
		for _, each := range strings.Split(view.Note, "\n") {
			for _, part := range terminal.Wrap(each, room-2) {
				under = append(under, "  "+s.Styled(part, "dim"))
			}
		}
	}
	page := max(1, s.Height()-5-len(keyLine(s, keys, s.Width(), ""))-len(under)-len(over))
	var drawn, keyed []int // the lines of the row the keys are on, and of its cell
	for i, line := range body {
		if line.row == view.Row {
			drawn = append(drawn, i)
			if slices.ContainsFunc(line.cells, func(cell matrixCell) bool { return cell.column == view.Column }) {
				keyed = append(keyed, i)
			}
		}
	}
	low, high := drawn[len(drawn)-1]-page+1, drawn[0]
	if low > high && len(keyed) > 0 { // taller than the page: Space acts on its cell
		low, high = keyed[0]-page+1, keyed[len(keyed)-1]
	}
	top := max(0, min(max(view.Top, low), high, len(body)-page))
	lines, spots := slices.Clone(over), make([]matrixRow, 2+len(over))
	for i := range spots {
		spots[i].row = -1
	}
	for _, row := range body[top:min(top+page, len(body))] {
		lines = append(lines, row.line)
		spots = append(spots, row)
	}
	return MatrixFrame{Panel(s, view.Title, time.Now().Format("15:04"), append(lines, under...), keys), top, spots}
}

// counted is count before its noun, one or many.
func counted(count int, one, many string) string {
	if count == 1 {
		return "1 " + one
	}
	return strconv.Itoa(count) + " " + many
}

// companiesBody is a line for each company shown, its name, then each of its models, `■` on in
// the accent, or `□` and dim where off; a model after the first that would pass the width, its space after
// aside, goes on a new line under the column where they began, its name cut to the room after
// it.  The keys' cell, column of the row at, is reversed (Screen.Toggle) and its row highlighted.
// Last, `+ add a company`.
func companiesBody(s terminal.Screen, shown []matrix.Company, on map[string]bool, at, column int) []matrixRow {
	room, lit, out := s.LayoutWidth(), "■", "□"
	if s.ASCII() {
		lit, out = "#", "-"
	}
	label := 0
	for _, company := range shown {
		label = max(label, terminal.Cells(company.Maker))
	}
	start := label + 4 // the models' first column: after a space, the name's cell and one
	var body []matrixRow
	for row, company := range shown {
		texts, kinds := []string{company.Maker}, []string{""}
		for _, model := range company.Models {
			mark, kind := lit, "accent"
			if !on[model[0]] {
				mark, kind = out, "dim"
			}
			texts, kinds = append(texts, mark+" "+terminal.Cut(model[1], room-start-2)), append(kinds, kind)
		}
		lines := []matrixRow{{line: " ", row: row}}
		for number, text := range texts {
			first, width := terminal.Cells(lines[len(lines)-1].line)+1, terminal.Cells(text)+2
			if number > 1 && first+width-2 > room { // its space after may go
				lines = append(lines, matrixRow{line: strings.Repeat(" ", start-1), row: row})
				first = start
			}
			line := &lines[len(lines)-1]
			line.line += s.Toggle(text, width, row == at && number == column, kinds[number])
			if number == 0 {
				line.line += strings.Repeat(" ", label-terminal.Cells(text))
			}
			line.cells = append(line.cells, matrixCell{first, first + width - 1, number})
		}
		for i := range lines {
			lines[i].line = strings.TrimRight(lines[i].line, " ")
			if row == at {
				lines[i].line = s.Highlight(lines[i].line, i == 0)
			}
		}
		body = append(body, lines...)
	}
	add := "  + add a company"
	if at == len(shown) {
		add = s.Highlight(add, true)
	}
	return append(body, matrixRow{line: add, row: len(shown)})
}
