package cli

import (
	"slices"
	"strings"
	"time"

	"agentkit/internal/menu"
	"agentkit/internal/motion"
	"agentkit/internal/terminal"
)

// configPage is `config · <name>`, a page `c` opens (menu.config_page): `page` gives its rows,
// asked again for every draw, false handing the page to Python, and `note` is said under them;
// read with `c`'s keys until Esc, true back where it opened.  ↑/↓, k/j, the wheel and the pointer
// move the highlight, the keys and the wheel through each page of a row taller than the page
// first, and a row gone from under it leaves it on the row of its label, else the nearest.  Space
// flips a mark, Enter opens what a row opens, and a click does what the row's Space does, else its
// Enter.  A row's list opens under it, the highlight on its first marked choice and moving through
// its choices alone: Space flips one, the list staying open, and Enter closes it, in a list that
// picks one first picking the lit choice, or on a choice that acts acts, the list asked again; Esc
// closes it, and so does a click on a row.  ← and → step a row that steps, and so does a click on
// their arrow; `move`, where given, names what ↑↓ and ←→ each move (menu.Page.Move).  The pointer
// off every row puts the highlight out, a key bringing it back where it was, Space, Enter, ← or →
// doing nothing more.  What a flip, a step or an act says stays under the rows until the next key.
// The page comes up as it opens and moves on its clock (menu.ConfigPage), a key ending what moves,
// and one gone back to is drawn as it is.
func configPage(name, note string, page func() ([]menu.PageRow, bool), keyboard *terminal.Keyboard, painter *terminal.Painter, move ...string) bool {
	view, clock := menu.Page{Name: name, Note: note, Move: move}, &motion.Clock{}
	frame := time.AfterFunc(time.Hour, keyboard.Wake) // each draw sets it to its next frame
	defer frame.Stop()
	defer painter.Forget()
	for {
		label := ""
		if view.At < len(view.Rows) {
			label = view.Rows[view.At].Label
		}
		rows, known := page()
		if !known {
			return false
		}
		if at := slices.IndexFunc(rows, func(row menu.PageRow) bool { return row.Label == label }); at >= 0 {
			view.At = at
		}
		view.Rows, view.At = rows, max(0, min(view.At, len(rows)-1))
		screen := keyboard.Screen()
		clock.Draw(time.Now())
		view.Motion, view.Clock = clock, time.Now().Format("15:04")
		if !screen.Moves() {
			view.Motion = nil
		}
		drawn := menu.ConfigPage(screen, view)
		view.Top = drawn.Top
		painter.Write(drawn.Lines, screen)
		if next, due := clock.Next(); due {
			frame.Reset(next)
		} else {
			frame.Stop()
		}
		key := keyboard.ReadKey()
		if view.Away && slices.Contains([]string{"space", "enter", "left", "right"}, key.Name) {
			view.Away = false // pressed with no highlight drawn: it only comes back where the keys left it
			continue
		}
		if key.Name != "wake" && key.Name != "again" {
			view.Away = false
		}
		if key.Name != "wake" && key.Name != "again" && key.Name != "pointer" {
			clock.Finish() // a key, not the pointer, ends what moves on its last frame
			view.Said = ""
		}
		open := view.Choices != nil
		switch {
		case key.Name == "esc" && open:
			view.Choices = nil
		case key.Name == "esc" || key.Name == "eof":
			return true
		case key.Name == "again":
			painter.Forget()
		case key.Name == "up" || key.Name == "char" && strings.EqualFold(key.Char, "k"):
			view.At, view.Choice, view.Top = drawn.Step(-1)
		case key.Name == "down" || key.Name == "char" && strings.EqualFold(key.Char, "j"):
			view.At, view.Choice, view.Top = drawn.Step(1)
		case key.Name == "pointer":
			mouse := key.Mouse
			if mouse.Button&64 != 0 {
				view.At, view.Choice, view.Top = drawn.Step(mouse.Notches)
			} else if row, choice, hit := drawn.Hit(mouse); hit {
				clicked := mouse.Released && mouse.Button&3 == 0
				// the pointer lights what the keys move through; a click on a row shuts the list
				if (choice >= 0) == open || clicked {
					view.At, view.Choice = row, choice
				}
				if clicked && choice < 0 {
					view.Choices = nil
				}
				if clicked {
					key.Name = "enter"
					if lit(view).Flip != nil {
						key.Name = "space"
					}
					if by := drawn.Arrow(mouse); by != 0 {
						key.Name = map[int]string{-1: "left", 1: "right"}[by]
					}
				}
			} else {
				view.Away = true
			}
		}
		if len(rows) == 0 {
			continue
		}
		switch row := lit(view); {
		case (key.Name == "left" || key.Name == "right") && row.Step != nil:
			if take := row.Step(map[string]int{"left": -1, "right": 1}[key.Name]); take != nil {
				view.Said = take()
			}
		case key.Name == "space" && row.Flip != nil:
			view.Said = row.Flip()
			if view.Choices != nil && !openList(&view) {
				return false
			}
		case key.Name == "enter" && row.Act != nil:
			view.Said = row.Act()
			if view.Choices != nil && !openList(&view) {
				return false
			}
		case key.Name == "enter" && view.Choices != nil:
			if row.Flip == nil {
				break // a line saying why the list holds none: only Esc shuts it
			}
			if !rows[view.At].Several {
				view.Said = row.Flip()
			}
			view.Choices = nil
		case key.Name == "enter" && row.List != nil:
			if !openList(&view) {
				return false
			}
			view.Lists++
			view.Choice = max(0, slices.IndexFunc(view.Choices, func(choice menu.PageRow) bool { return choice.On && choice.Flip != nil }))
		case key.Name == "enter" && row.Open != nil:
			if !row.Open() {
				return false
			}
			clock = &motion.Clock{} // back, the page is drawn as it is
			clock.Finish()
		}
	}
}

// lit is the row the keys are on, or with a list open its choice.
func lit(view menu.Page) menu.PageRow {
	if view.Choices != nil {
		return view.Choices[view.Choice]
	}
	return view.Rows[view.At]
}

// openList asks the list of the row the keys are on for its choices, as it opens and after each
// flip or act, the highlight kept on a choice; none shuts it.  False where they are Python's.
func openList(view *menu.Page) bool {
	choices, known := view.Rows[view.At].List()
	if len(choices) == 0 {
		choices = nil
	}
	view.Choices, view.Choice = choices, min(view.Choice, max(0, len(choices)-1))
	return known
}
