package cli

import (
	"slices"
	"strings"

	"agentkit/internal/matrix"
	"agentkit/internal/menu"
	"agentkit/internal/quality"
	"agentkit/internal/terminal"
)

// menuCompanyList is `p` on the models screen, `<title> · models` (menu.company_list), until Esc:
// ↑/↓ move between your companies and `+ add a company`, ←/→ between a company's name and its
// models, and ⏎ on a company does nothing.  False where Python ak takes it over, having written
// nothing: Space or a click on a company's cell, an Esc that drops a company, and `a`, Space, ⏎
// or a click on `+ add a company` change the config.
func menuCompanyList(title string, keyboard *terminal.Keyboard, painter *terminal.Painter) bool {
	view := menu.CompanyListView{Title: title + " · models"}
	var was []matrix.Company // the rows last drawn, so the keys stay on their company
	drawn := false           // or on `+ add a company`, though none was drawn above it
	defer painter.Forget()
	for {
		rows := matrix.Stored().Rows // the boards may land meanwhile, as Python reads them per key
		var err error
		if view.Listed, view.Yours, err = matrix.Companies(rows); err != nil {
			return false
		}
		if view.On, _, err = matrix.Compared(rows); err != nil {
			return false
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
		view.Away = false
		switch {
		case key.Name == "esc" || key.Name == "eof":
			return !drops(rows, view)
		case key.Name == "up" || key.Name == "char" && strings.EqualFold(key.Char, "k"):
			view.Row = max(0, view.Row-1)
		case key.Name == "down" || key.Name == "char" && strings.EqualFold(key.Char, "j"):
			view.Row = min(len(shown), view.Row+1)
		case key.Name == "left":
			view.Column = max(0, view.Column-1)
		case key.Name == "right":
			view.Column = min(models, view.Column+1)
		case key.Name == "space" || key.Name == "char" && key.Char == "a":
			return false
		case key.Name == "enter" && view.Row == len(shown):
			return false
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
			if key.Mouse.Released && key.Mouse.Button&3 == 0 && (column >= 0 || row == len(shown)) {
				return false
			}
		}
	}
}

// drops is whether Esc leaves a company out of `companies`, Python's to write: one of yours the
// lineup rows name with no listed model on, so one whose releases have no score goes too.
func drops(rows []quality.Row, view menu.CompanyListView) bool {
	on := func(one matrix.Company) bool {
		return slices.ContainsFunc(one.Models, func(model [2]string) bool { return view.On[model[0]] })
	}
	return slices.ContainsFunc(rows, func(row quality.Row) bool {
		return slices.Contains(view.Yours, row.Maker) &&
			!slices.ContainsFunc(view.Listed, func(one matrix.Company) bool { return one.Maker == row.Maker && on(one) })
	})
}
