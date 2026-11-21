package cli

import (
	"slices"
	"strings"

	"agentkit/internal/config"
	"agentkit/internal/matrix"
	"agentkit/internal/menu"
	"agentkit/internal/terminal"
)

// companyAdded is `a` on the company list (menu.company_list): the company picked on its page
// (menuCompanyAdd) after yours, all its listed models on, as they leave `models_off`, saved at once
// (modelsListed).  What to say and that company, "" for none; false, with nothing written, leaves
// it to Python.
func companyAdded(view menu.CompanyListView, keyboard *terminal.Keyboard, painter *terminal.Painter) (string, string, bool) {
	others := slices.DeleteFunc(slices.Clone(view.Listed), func(one matrix.Company) bool { return slices.Contains(view.Yours, one.Maker) })
	at := menuCompanyAdd(view.Title+" · add a company", others, keyboard, painter)
	if at < 0 {
		return "", "", true
	}
	_, off, err := config.ModelList()
	if err != nil {
		return "", "", false
	}
	off = slices.DeleteFunc(off, func(slug string) bool {
		return slices.ContainsFunc(others[at].Models, func(model [2]string) bool { return model[0] == slug })
	})
	said, carried := modelsListed(append(slices.Clone(view.Yours), others[at].Maker), off)
	return said, others[at].Maker, carried
}

// menuCompanyAdd is `<title> · add a company` (menu.company_add) over `others` until ⏎ or a click
// picks the row the keys are on, or Esc goes back: that row, or -1.
func menuCompanyAdd(title string, others []matrix.Company, keyboard *terminal.Keyboard, painter *terminal.Painter) int {
	at, top, away := 0, 0, false
	var pointer terminal.Mouse // where it was read last while it has the highlight
	var clicks terminal.Clicks
	for {
		screen := keyboard.Screen()
		frame := menu.CompanyAddFrame(screen, title, others, at, top, away, pointer)
		top = frame.Top
		painter.Write(frame.Lines, screen)
		key, clicked := clicks.Key(keyboard.ReadKey())
		if clicked {
			key = frame.Pressed(key) // a key-line item does what its key does
		}
		switch {
		case key.Name == "again":
			painter.Forget()
			keyboard.Unread(pointer.Resting()...) // what the new draw puts under the pointer has it
			continue
		case key.Name == "wake", key.Name == "": // the boards landed, or the left button going down (read_key)
			continue
		case away && (key.Name == "space" || key.Name == "enter"):
			away, pointer = false, terminal.Mouse{} // pressed with no highlight drawn: it only comes back where the keys left it
			continue
		}
		hadPointer := pointer != (terminal.Mouse{})
		away, pointer = false, terminal.Mouse{} // a key has the highlight
		switch {
		case key.Name == "esc" || key.Name == "eof":
			return -1
		case key.Name == "up" || key.Name == "char" && strings.EqualFold(key.Char, "k"):
			at = max(0, at-1)
		case key.Name == "down" || key.Name == "char" && strings.EqualFold(key.Char, "j"):
			at = max(0, min(len(others)-1, at+1))
		case key.Name == "enter" && len(others) > 0:
			return at
		case key.Name == "pointer" && key.Mouse.Button&64 != 0:
			at = max(0, min(len(others)-1, at+key.Mouse.Notches))
		case key.Name == "pointer":
			if row, _, hit := frame.Hit(key.Mouse); hit {
				pointer, at = key.Mouse, row
				if clicked {
					return at
				}
			} else if !clicked || hadPointer {
				away, pointer = true, key.Mouse
			}
		}
	}
}
