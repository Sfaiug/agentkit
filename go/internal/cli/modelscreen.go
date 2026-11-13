package cli

import (
	"strings"
	"sync"

	"agentkit/internal/matrix"
	"agentkit/internal/menu"
	"agentkit/internal/quality"
	"agentkit/internal/terminal"
)

var readingModels sync.Mutex // closing and reopening the page shares the boards' reader

// title is the name `c` gives this page; a row's why, which it opens, carries it too.  False
// where Python ak takes the page over, having written nothing.
func menuModels(title string, c *matrix.Configuration, keyboard *terminal.Keyboard, painter *terminal.Painter) bool {
	type reading struct {
		found *matrix.Matrix
		err   error
	}
	found := matrix.Stored()
	var compared map[string]bool
	var total int // the listed releases of your companies
	var answer map[string]*quality.Said
	// each role's answer over the lineup found
	answered := func() (err error) {
		if compared, total, err = matrix.Compared(found.Rows); err != nil {
			return err
		}
		shares, err := matrix.Shares()
		if err != nil {
			return err
		}
		answer, err = matrix.Answer(found.Rows, compared, shares)
		return err
	}
	if answered() != nil {
		return false
	}
	read := make(chan reading, 1)
	go func() {
		readingModels.Lock()
		defer readingModels.Unlock()
		found, err := matrix.Refresh(false)
		read <- reading{found, err}
		keyboard.Wake()
	}()
	view := menu.ModelsView{Title: title} // `▸` on the orchestrator, where the boards landing leaves it
	defer painter.Forget()
	for {
		select {
		case fresh := <-read:
			read = nil
			if fresh.err != nil {
				view.Note = "the boards were not read: " + fresh.err.Error()
			} else {
				found = fresh.found
				if answered() != nil {
					return false
				}
			}
		default:
		}
		s := keyboard.Screen()
		used := c.Uses(answer)
		view.Answer, view.Uses, view.Models = answer, used, c.Models
		view.Compared, view.Total, view.Fetched = compared, total, found.Fetched
		frame := menu.ModelsFrame(s, view)
		view.Top = frame.Top
		painter.Write(frame.Lines, s)
		key := keyboard.ReadKey()
		switch {
		case key.Name == "wake": // the boards landed: drawn again
			continue
		case view.Away && key.Name == "enter":
			view.Away = false // pressed with no `▸` drawn: it only comes back where the keys left it
			continue
		}
		view.Away = false
		switch {
		case key.Name == "esc" || key.Name == "eof":
			return true
		case key.Name == "left" || key.Name == "right":
			return false // a role's next cheaper or better choice: Python's take (menu.take_choice)
		case key.Name == "again":
			painter.Forget()
		case key.Name == "up" || key.Name == "char" && strings.EqualFold(key.Char, "k"):
			view.At = menu.RoleStep(view.At, -1)
		case key.Name == "down" || key.Name == "char" && strings.EqualFold(key.Char, "j"):
			view.At = menu.RoleStep(view.At, 1)
		case key.Name == "pointer":
			mouse := key.Mouse
			if mouse.Button&64 != 0 {
				view.At = menu.RoleStep(view.At, mouse.Notches)
			} else if row, _, hit := frame.Hit(mouse); hit {
				view.At = row
				if mouse.Released && mouse.Button&3 == 0 {
					key.Name = "enter"
				}
			} else {
				view.Away = true
			}
		case key.Name == "char" && key.Char == "p":
			said, carried := menuCompanyList(title, keyboard, painter)
			if !carried {
				return false
			}
			if answered() != nil { // left, answered again over what is on
				return false
			}
			view.Note = said
		}
		// the why of the row the role uses, else of its first choice
		if role := quality.Roles[view.At]; key.Name == "enter" {
			if row := used[role].Row; row != nil {
				modelWhy(title, answer[role], row, role, keyboard, painter)
			} else if choices := answer[role].Choices; len(choices) > 0 {
				modelWhy(title, answer[role], choices[0], role, keyboard, painter)
			}
		}
	}
}
