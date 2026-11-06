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

// A PageFrame is a draw of a page, and where the pointer finds its rows.
type PageFrame struct {
	Lines []string
	Top   int
	rows  []int // each screen row's row, -1 for none
}

// Hit is the row under the pointer; false off every row.
func (f PageFrame) Hit(mouse terminal.Mouse) (int, bool) {
	if mouse.Row <= 0 || mouse.Row > len(f.rows) || f.rows[mouse.Row-1] < 0 {
		return 0, false
	}
	return f.rows[mouse.Row-1], true
}

// ConfigPage draws a page `c` opens as page_body draws one: each row's label, then its value lined
// up past the widest label and wrapped at a word under itself, never cut, or folded under its
// label where a word is too wide beside it.  The highlighted row's lines stay on the page, the
// note under the rows, and the key line names what Space and Enter do there.
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
	// the key line and the note stay on the screen, and so do the highlighted row's lines
	page := max(1, s.Height()-5-len(keyLine(s, keys, s.Width(), ""))-len(under))
	first, last := slices.Index(rows, view.At), -1
	for i, row := range rows {
		if row == view.At {
			last = i
		}
	}
	top := max(0, min(max(view.Top, last-page+1), max(0, first), max(0, len(body)-page)))
	shown := min(len(body), top+page)
	return PageFrame{Panel(s, "config · "+view.Name, view.Clock, append(slices.Clone(body[top:shown]), under...), keys),
		top, append([]int{-1, -1}, rows[top:shown]...)}
}
