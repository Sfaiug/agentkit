package cli

import (
	"slices"
	"strings"
	"time"

	"agentkit/internal/menu"
	"agentkit/internal/terminal"
)

// configPage is `config · <name>`, a page `c` opens (menu.config_page): `page` gives its rows,
// asked again for every draw, false handing the page to Python; read with `c`'s keys until Esc,
// true back where it opened.  ↑/↓, k/j, the wheel and the pointer move the highlight, the keys
// and the wheel through each page of a row taller than the page first, and a row gone from under
// it leaves it on the row of its label, else the nearest; Space flips a mark,
// Enter opens what a row opens, and a click does what the row's Space does, else its Enter.
// What a flip says stays under the rows until the next key.
func configPage(name string, page func() ([]menu.PageRow, bool), keyboard *terminal.Keyboard, painter *terminal.Painter) bool {
	view := menu.Page{Name: name}
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
		view.Clock = time.Now().Format("15:04")
		screen := keyboard.Screen()
		frame := menu.ConfigPage(screen, view)
		view.Top = frame.Top
		painter.Write(frame.Lines, screen)
		key := keyboard.ReadKey()
		if key.Name != "pointer" && key.Name != "again" {
			view.Note = ""
		}
		switch {
		case key.Name == "esc" || key.Name == "eof":
			return true
		case key.Name == "again":
			painter.Forget()
		case key.Name == "up" || key.Name == "char" && strings.EqualFold(key.Char, "k"):
			view.At, view.Top = frame.Step(-1)
		case key.Name == "down" || key.Name == "char" && strings.EqualFold(key.Char, "j"):
			view.At, view.Top = frame.Step(1)
		case key.Name == "pointer":
			mouse := key.Mouse
			if mouse.Button&64 != 0 {
				step := -1
				if mouse.Button&1 != 0 {
					step = 1
				}
				view.At, view.Top = frame.Step(step)
			} else if row, hit := frame.Hit(mouse); hit {
				view.At = row
				if mouse.Released && mouse.Button&3 == 0 {
					key.Name = "enter"
					if rows[row].Flip != nil {
						key.Name = "space"
					}
				}
			}
		}
		if len(rows) == 0 {
			continue
		}
		switch row := rows[view.At]; {
		case key.Name == "space" && row.Flip != nil:
			view.Note = row.Flip()
		case key.Name == "enter" && row.Open != nil:
			if !row.Open() {
				return false
			}
		}
	}
}
