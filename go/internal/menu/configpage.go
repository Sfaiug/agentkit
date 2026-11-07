package menu

import (
	"fmt"
	"slices"
	"strings"

	"agentkit/internal/motion"
	"agentkit/internal/terminal"
)

// A PageRow is a row of a page `c` opens (menu.config_page's), or a choice of the list a row opens
// under it: its label, in its colour where it has one, its value, and what its keys do, nil where
// they do nothing.  A mark leads the value of a row Space flips, full while On: ● on a row and on a
// choice of a list that picks one, ■ on a choice of a list of several; a choice that acts is
// followed by its word, dim.  A choice no key acts on is a line saying why the list holds none, dim.
type PageRow struct {
	Label, Value, Colour string
	On                   bool
	Flip                 func() string // Space or a click: flips the mark, and what to say under the rows
	Open                 func() bool   // Enter or a click: opens what the row opens, false where that is Python's
	// a choice's Enter or click, the key line naming it Does: what to say under the rows, the list
	// asked again after it
	Act  func() string
	Does string
	// Enter or a click: the choices the row opens under it, asked as it opens and after each flip
	// or act, false where they are Python's
	List    func() ([]PageRow, bool)
	Several bool // List's choices are each taken in or out, Enter closing it; else Enter picks the lit one
	// Enter or a click: a field opens under the row, Placeholder dim in it until a key types over
	// it; its Enter gives Field what was typed, and what to say under the rows
	Field       func(typed string) string
	Placeholder string
}

// Page is a page `c` opens, `config · <Name>`, as one draw has it.
type Page struct {
	Name       string
	Rows       []PageRow
	Choices    []PageRow // the list open under the row the keys are on: none while it is shut
	Typed      *string   // what is typed in the field open under the row the keys are on: nil while it is shut
	At, Choice int       // the row the keys are on, and with a list open its choice
	Lists      int       // how many lists the page has opened: the one open comes up as it is news
	Top        int       // the first line shown
	Clock      string
	Said, Note string        // what the last key's act said, and the page's own note
	Motion     *motion.Clock // nil, all still
}

// A PageFrame is a draw of a page, and where the keys and the pointer go from it.
type PageFrame struct {
	Lines []string
	Top   int
	at    pageEntry   // what the keys are on
	page  int         // how many lines of rows are shown
	lines []pageEntry // each line's
}

// A pageEntry is a page's row, or a choice of the list open under it; choice -1 for the row, and
// typedIn for the field open under it.
type pageEntry struct{ row, choice int }

const typedIn = -2

// Hit is the row under the pointer, and its open list's choice there, -1 for none; false off
// every row.
func (f PageFrame) Hit(mouse terminal.Mouse) (row, choice int, ok bool) {
	line := f.Top + mouse.Row - 3 // the rows start on the screen's third row, under the header
	if mouse.Row < 3 || line >= min(len(f.lines), f.Top+f.page) {
		return 0, -1, false
	}
	return f.lines[line].row, f.lines[line].choice, true
}

// Step is the row the keys are on, its open list's choice and the first line shown, `step` on as
// ↑/↓ and the wheel move, through an open list's choices alone and as far as there are: a row
// going on past the page that way turns to its next page before they leave it.
func (f PageFrame) Step(step int) (row, choice, top int) {
	past := f.Top - 1
	if step > 0 {
		past = f.Top + f.page
	}
	if past >= 0 && past < len(f.lines) && f.lines[past] == f.at {
		return f.at.row, f.at.choice, pageTop(f.lines, f.at, f.Top+step*f.page, f.page)
	}
	var through []pageEntry // what the keys move through, each once: the open list's choices, else the rows
	for _, line := range f.lines {
		if (line.choice >= 0) == (f.at.choice >= 0) && (len(through) == 0 || through[len(through)-1] != line) {
			through = append(through, line)
		}
	}
	at := slices.Index(through, f.at)
	if at < 0 {
		return f.at.row, f.at.choice, f.Top
	}
	next := through[max(0, min(at+step, len(through)-1))]
	return next.row, next.choice, f.Top
}

// pageTop is the first line shown of `lines`, a page `page` lines high, from `top`: moved the least
// that shows every line of `at`, or one of a row taller than the page, never past the last page
// (matrix_page's).
func pageTop(lines []pageEntry, at pageEntry, top, page int) int {
	first, last := slices.Index(lines, at), -1
	for i, line := range lines {
		if line == at {
			last = i
		}
	}
	lo, hi := last-page+1, first
	if lo > hi {
		lo, hi = first-page+1, last
	}
	return max(0, min(max(top, lo), hi, len(lines)-page))
}

// ConfigPage draws a page `c` opens as page_body draws one: each row's label, then its value lined
// up past the widest label and wrapped at a word under itself, never cut, or folded under its
// label where a word is too wide beside it; an open list's choices under its row, indented, or an
// open field under the row's last line (fieldLine).  The highlighted row stays on the page, a page
// of it where it is taller, or the field, no row lit; what was said and the note under the rows,
// and the key line names what Space and Enter do there.  On the clock the page comes up as it
// opens (comeUp), a list comes up under its row, and a mark that flips goes through its half
// (motion.Clock.Mark).
func ConfigPage(s terminal.Screen, view Page) PageFrame {
	room, wide, clock := s.LayoutWidth(), 0, view.Motion
	for _, row := range view.Rows {
		wide = max(wide, terminal.Cells(row.Label))
	}
	at := pageEntry{view.At, -1}
	if len(view.Choices) > 0 {
		at.choice = view.Choice
	}
	if view.Typed != nil {
		at.choice = typedIn // the field stays on the page, and no row is lit
	}
	_, opening := clock.Moved("opened", view.Lists, motion.Open)
	var body []string
	var lines []pageEntry
	type part struct{ text, kind string }
	draw := func(row PageRow, entry pageEntry, marks string) {
		label := row.Label
		if row.Colour != "" {
			label = s.Styled(label, row.Colour)
		}
		lead := "  " + terminal.Pad(label, wide) + "  "
		if entry.choice >= 0 {
			lead = "    "
		}
		left := max(1, room-terminal.Cells(lead))
		parts := []part{{row.Value, ""}}
		if row.Flip != nil {
			glyphs := []rune(marks)
			mark := part{string(glyphs[1]), "dim"}
			if row.On {
				mark = part{string(glyphs[0]), "accent"}
			}
			// keyed by the list too: one opened again is drawn as it is, as Python's look forgets it
			mark.text = clock.Mark(fmt.Sprint("mark ", entry.row, " ", entry.choice, " ", view.Lists), mark.text)
			parts = append([]part{mark}, parts...)
		} else if row.Act != nil {
			parts = append(parts, part{row.Does, "dim"})
		} else if entry.choice >= 0 {
			parts[0].kind = "dim" // why the list holds no choice
		}
		folded := entry.choice < 0 && slices.ContainsFunc(parts, func(p part) bool {
			return slices.ContainsFunc(strings.Fields(p.text), func(word string) bool { return terminal.Cells(word) > left })
		})
		if folded {
			line := "  " + terminal.Cut(row.Label, room-2)
			if row.Colour != "" {
				line = "  " + s.Styled(terminal.Cut(row.Label, room-2), row.Colour)
			}
			if entry == at {
				line = s.Highlight(line, true)
			}
			body, lines = append(body, line), append(lines, entry)
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
			if entry == at {
				line = s.Highlight(line, number == 0 && !folded)
			}
			if entry.choice >= 0 {
				line = s.Fade(line, 1-opening) // the list comes up under its row
			}
			body, lines = append(body, line), append(lines, entry)
		}
	}
	marks := func(several bool) string {
		switch {
		case several && s.ASCII():
			return "#-"
		case several:
			return "■□"
		case s.ASCII():
			return "*."
		}
		return "●○"
	}
	for i, row := range view.Rows {
		draw(row, pageEntry{i, -1}, marks(false))
		if i == view.At {
			for n, choice := range view.Choices {
				draw(choice, pageEntry{i, n}, marks(row.Several))
			}
			if view.Typed != nil {
				body, lines = append(body, fieldLine(s, *view.Typed, row.Placeholder)), append(lines, at)
			}
		}
	}

	keys := "↑↓←→ move   "
	if view.Typed != nil {
		keys = "⏎ save   " // typed in, nothing moves
	} else if view.At < len(view.Rows) {
		lit, enter := view.Rows[view.At], ""
		switch {
		case at.choice >= 0:
			if lit.Several {
				enter = "close"
			} else {
				enter = "pick"
			}
			if lit = view.Choices[at.choice]; lit.Act != nil {
				enter = lit.Does
			} else if lit.Flip == nil {
				enter = ""
			}
		case lit.Open != nil || lit.List != nil || lit.Field != nil:
			enter = "open"
		}
		if lit.Flip != nil {
			keys += "␣ mark   "
		}
		if enter != "" {
			keys += "⏎ " + enter + "   "
		}
	}
	keys += "esc back"
	if s.ASCII() {
		keys = strings.NewReplacer("↑↓←→", "arrows", "␣", "space", "⏎", "enter").Replace(keys)
	}
	var under []string
	for _, note := range []string{view.Said, view.Note} {
		for _, said := range strings.Split(note, "\n") {
			for _, line := range terminal.Wrap(said, room-2) {
				under = append(under, "  "+s.Styled(line, "dim"))
			}
		}
	}
	if len(under) > 0 {
		under = append([]string{""}, under...)
	}
	// the key line and the note stay on the screen, and so does the highlighted row
	page := max(1, s.Height()-5-len(keyLine(s, keys, s.Width(), ""))-len(under))
	top := pageTop(lines, at, view.Top, page)
	shown := min(len(body), top+page)
	title := "config · " + view.Name
	return PageFrame{comeUp(s, Panel(s, title, view.Clock, append(slices.Clone(body[top:shown]), under...), keys), title, clock.Risen()),
		top, at, page, lines}
}
