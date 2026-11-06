package menu

import (
	"slices"
	"strings"

	"agentkit/internal/terminal"
)

// A PageRow is a row of a page `c` opens (menu.config_page's): its label and value, and what its
// keys do, nil where they do nothing.  A mark leads the value of a row Space flips, ● while On.
type PageRow struct {
	Label, Value string
	On           bool
	Flip         func() string // Space or a click: flips the mark, and what to say under the rows
	Open         func() bool   // Enter or a click: opens what the row opens, false where that is Python's
}

// Page is a page `c` opens, `config · <Name>`, as one draw has it.
type Page struct {
	Name        string
	Rows        []PageRow
	At, Top     int // the row the keys are on, and the first line shown
	Clock, Note string
}

// A PageFrame is a draw of a page, and where the keys and the pointer go from it.
type PageFrame struct {
	Lines    []string
	Top      int
	at, page int   // the row the keys are on, and how many lines of rows are shown
	rows     []int // each line's row
}

// Hit is the row under the pointer; false off every row.
func (f PageFrame) Hit(mouse terminal.Mouse) (int, bool) {
	line := f.Top + mouse.Row - 3 // the rows start on the screen's third row, under the header
	if mouse.Row < 3 || line >= min(len(f.rows), f.Top+f.page) {
		return 0, false
	}
	return f.rows[line], true
}

// Step is the row the keys are on and the first line shown, `step` rows on as ↑/↓ and the wheel
// move, as far as there are rows: a row going on past the page that way turns to its next page
// before they leave it.
func (f PageFrame) Step(step int) (int, int) {
	past := f.Top - 1
	if step > 0 {
		past = f.Top + f.page
	}
	if past >= 0 && past < len(f.rows) && f.rows[past] == f.at {
		return f.at, pageTop(f.rows, f.at, f.Top+step*f.page, f.page)
	}
	if len(f.rows) == 0 {
		return f.at, f.Top
	}
	return max(f.rows[0], min(f.at+step, f.rows[len(f.rows)-1])), f.Top
}

// pageTop is the first line shown of `rows`, a page `page` lines high, from `top`: moved the least
// that shows every line of the row `at`, or one of a row taller than the page, never past the last
// page (matrix_page's).
func pageTop(rows []int, at, top, page int) int {
	first, last := slices.Index(rows, at), -1
	for i, row := range rows {
		if row == at {
			last = i
		}
	}
	lo, hi := last-page+1, first
	if lo > hi {
		lo, hi = first-page+1, last
	}
	return max(0, min(max(top, lo), hi, len(rows)-page))
}

// ConfigPage draws a page `c` opens as page_body draws one: each row's label, then its value lined
// up past the widest label and wrapped at a word under itself, never cut, or folded under its
// label where a word is too wide beside it.  The highlighted row stays on the page, a page of it
// where it is taller, the note under the rows, and the key line names what Space and Enter do there.
func ConfigPage(s terminal.Screen, view Page) PageFrame {
	room, wide := s.LayoutWidth(), 0
	for _, row := range view.Rows {
		wide = max(wide, terminal.Cells(row.Label))
	}
	var body []string
	var rows []int
	put := func(line string, row int) {
		body, rows = append(body, line), append(rows, row)
	}
	type part struct{ text, kind string }
	for i, row := range view.Rows {
		lead := "  " + terminal.Pad(row.Label, wide) + "  "
		left := max(1, room-terminal.Cells(lead))
		parts := []part{{row.Value, ""}}
		if row.Flip != nil {
			mark := part{"●", "accent"}
			if !row.On {
				mark = part{"○", "dim"}
			}
			if s.ASCII() {
				mark.text = strings.NewReplacer("●", "*", "○", ".").Replace(mark.text)
			}
			parts = append([]part{mark}, parts...)
		}
		folded := slices.ContainsFunc(parts, func(p part) bool {
			return slices.ContainsFunc(strings.Fields(p.text), func(word string) bool { return terminal.Cells(word) > left })
		})
		if folded {
			line := "  " + terminal.Cut(row.Label, room-2)
			if i == view.At {
				line = s.Highlight(line, true)
			}
			put(line, i)
			lead, left = "    ", max(1, room-4)
		}
		wrapped, used := [][]string{nil}, 0
		for _, p := range parts {
			for _, piece := range terminal.Wrap(p.text, left) {
				if used > 0 && used+1+terminal.Cells(piece) > left {
					wrapped, used = append(wrapped, nil), 0
				}
				if used > 0 {
					used++
				}
				used += terminal.Cells(piece)
				if p.kind != "" {
					piece = s.Styled(piece, p.kind)
				}
				wrapped[len(wrapped)-1] = append(wrapped[len(wrapped)-1], piece)
			}
		}
		for number, pieces := range wrapped {
			if number > 0 {
				lead = strings.Repeat(" ", terminal.Cells(lead))
			}
			line := strings.TrimRight(lead+strings.Join(pieces, " "), " ")
			if i == view.At {
				line = s.Highlight(line, number == 0 && !folded)
			}
			put(line, i)
		}
	}

	keys := "↑↓←→ move   "
	if view.At < len(view.Rows) {
		if view.Rows[view.At].Flip != nil {
			keys += "␣ mark   "
		}
		if view.Rows[view.At].Open != nil {
			keys += "⏎ open   "
		}
	}
	keys += "esc back"
	if s.ASCII() {
		keys = strings.NewReplacer("↑↓←→", "arrows", "␣", "space", "⏎", "enter").Replace(keys)
	}
	var under []string
	if view.Note != "" {
		under = append(under, "")
		for _, line := range terminal.Wrap(view.Note, room-2) {
			under = append(under, "  "+s.Styled(line, "dim"))
		}
	}
	// the key line and the note stay on the screen, and so does the highlighted row
	page := max(1, s.Height()-5-len(keyLine(s, keys, s.Width(), ""))-len(under))
	top := pageTop(rows, view.At, view.Top, page)
	shown := min(len(body), top+page)
	return PageFrame{Panel(s, "config · "+view.Name, view.Clock, append(slices.Clone(body[top:shown]), under...), keys),
		top, view.At, page, rows}
}
