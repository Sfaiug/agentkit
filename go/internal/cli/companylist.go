package cli

import (
	"slices"
	"strings"

	"agentkit/internal/matrix"
	"agentkit/internal/menu"
	"agentkit/internal/terminal"
)

// menuCompanyList is `p` on the models screen, `<title> · models` (menu.company_list), until Esc:
// ↑/↓ move between your companies and `+ add a company`, ←/→ between a company's name and its
// models, ⏎ on a company does nothing, and Space or a click on a cell turns it on or off
// (turned).  `a`, or Space, ⏎ or a click on `+ add a company`, adds one all on (companyAdded), the
// keys landing on its name.  Esc drops each company left with none on (dropped).  What to say back
// on the models screen, or ""; false where Python ak takes it over, having written nothing: a
// change Go cannot save (seat.SaveWhole).
func menuCompanyList(title string, keyboard *terminal.Keyboard, painter *terminal.Painter) (string, bool) {
	view := menu.CompanyListView{Title: title + " · models"}
	var was []matrix.Company // the rows last drawn, so the keys stay on their company
	drawn := false           // or on `+ add a company`, though none was drawn above it
	defer painter.Forget()
	for {
		rows := matrix.Stored().Rows // the boards may land meanwhile, as Python reads them per key
		var err error
		if view.Listed, view.Yours, err = matrix.Companies(rows); err != nil {
			return "", false
		}
		if view.On, _, err = matrix.Compared(rows); err != nil {
			return "", false
		}
		shown := view.Shown()
		if view.Row < len(was) {
			maker := was[view.Row].Maker
			view.Row = max(0, slices.IndexFunc(shown, func(one matrix.Company) bool { return one.Maker == maker }))
		} else if drawn {
			view.Row = len(shown)
		}
		was, drawn = shown, true
		models := 0
		if view.Row < len(shown) {
			models = len(shown[view.Row].Models)
		}
		view.Column = min(view.Column, models)
		screen := keyboard.Screen()
		frame := menu.CompanyListFrame(screen, view)
		view.Top = frame.Top
		painter.Write(frame.Lines, screen)
		key := keyboard.ReadKey()
		switch {
		case key.Name == "again":
			painter.Forget()
			continue
		case key.Name == "wake": // the boards landed: drawn again
			continue
		case view.Away && (key.Name == "space" || key.Name == "enter"):
			view.Away = false // pressed with no highlight drawn: it only comes back where the keys left it
			continue
		}
		if key.Name != "pointer" || key.Mouse.Released || key.Mouse.Button&64 != 0 {
			view.Note = "" // the pointer passing over, or a button going down, keeps what was said
		}
		view.Away = false
		switch {
		case key.Name == "esc" || key.Name == "eof":
			return dropped(rows, view)
		case key.Name == "up" || key.Name == "char" && strings.EqualFold(key.Char, "k"):
			view.Row = max(0, view.Row-1)
		case key.Name == "down" || key.Name == "char" && strings.EqualFold(key.Char, "j"):
			view.Row = min(len(shown), view.Row+1)
		case key.Name == "left":
			view.Column = max(0, view.Column-1)
		case key.Name == "right":
			view.Column = min(models, view.Column+1)
		case key.Name == "char" && key.Char == "a",
			(key.Name == "space" || key.Name == "enter") && view.Row == len(shown):
			key.Name = "add"
		case key.Name == "pointer" && key.Mouse.Button&64 != 0:
			view.Row = max(0, min(len(shown), view.Row+key.Mouse.Notches))
		case key.Name == "pointer":
			row, column, hit := frame.Hit(key.Mouse)
			if !hit {
				view.Away = true
				continue
			}
			view.Row = row
			if column >= 0 { // off its cells the column stays
				view.Column = column
			}
			clicked := key.Mouse.Released && key.Mouse.Button&3 == 0
			if clicked && row == len(shown) {
				key.Name = "add"
			}
			if clicked && column >= 0 {
				key.Name = "space"
			}
		}
		if key.Name == "add" {
			var added string
			var carried bool
			if view.Note, added, carried = companyAdded(view, keyboard, painter); !carried {
				return "", false
			}
			if added != "" { // the keys land on its name, the row it takes as drawn again
				was, view.Row, view.Column = append(was, matrix.Company{Maker: added}), len(was), 0
			}
		}
		if key.Name == "space" {
			var carried bool
			if view.Note, carried = turned(shown[view.Row].Models, view.Column, view.Yours); !carried {
				return "", false
			}
		}
	}
}
