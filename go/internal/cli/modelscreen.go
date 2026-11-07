package cli

import (
	"strings"
	"sync"

	"agentkit/internal/config"
	"agentkit/internal/matrix"
	"agentkit/internal/menu"
	"agentkit/internal/quality"
	"agentkit/internal/seat"
	"agentkit/internal/terminal"
)

var readingModels sync.Mutex // closing and reopening the page shares the boards' reader

// title is the name `c` gives this page; a row's why, which it opens, carries it too.  False
// where Python ak takes the page over, having written nothing.
func menuModels(session, title string, c *matrix.Configuration, keyboard *terminal.Keyboard, painter *terminal.Painter) bool {
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
	var rows []*quality.Rating
	var roles []string
	var colours map[string]string
	pointing := false
	at, top, note := -1, 0, ""
	// The boards landing leaves the pointer on the row it was on, as Python's does; where that row is
	// gone, on its role's pick, the first role's before any.
	lineup := func() {
		colours = modelColours(found.Rows)
		role, was := quality.Roles[0], quality.Row{}
		if at >= 0 && at < len(rows) {
			role, was = roles[at], rows[at].Row
		}
		rows, roles, at = nil, nil, -1
		pick, first := -1, -1
		for _, each := range quality.Roles {
			for _, row := range answer[each].Front {
				if each == role {
					if at < 0 && row.Release == was.Release && row.Effort == was.Effort {
						at = len(rows)
					}
					if pick < 0 && row == answer[each].Pick {
						pick = len(rows)
					}
					if first < 0 {
						first = len(rows)
					}
				}
				rows, roles = append(rows, row), append(roles, each)
			}
		}
		if at < 0 {
			at = pick
		}
		if at < 0 {
			at = first
		}
		if at < 0 && len(rows) > 0 {
			at = 0
		}
	}
	lineup()
	defer painter.Forget()
	for {
		select {
		case fresh := <-read:
			read = nil
			if fresh.err != nil {
				note = "the boards were not read: " + fresh.err.Error()
			} else {
				found = fresh.found
				if answered() != nil {
					return false
				}
				lineup()
			}
		default:
		}
		s := keyboard.Screen()
		light := menu.ModelLight{}
		if pointing && at >= 0 && at < len(rows) {
			light = menu.ModelLight{Maker: rows[at].Maker, Colour: colours[rows[at].Maker]}
		}
		frame := menu.ModelsFrame(s, title, menu.ModelsSaid(s, answer, found.Rows),
			compared, total, found.Fetched, at, top, note, light)
		top = frame.Top
		painter.Write(frame.Lines, s)
		key := keyboard.ReadKey()
		switch {
		case key.Name == "esc" || key.Name == "eof":
			return true
		case key.Name == "again":
			painter.Forget()
		case key.Name == "up" || key.Name == "char" && strings.EqualFold(key.Char, "k"):
			pointing = true
			at = max(0, at-1)
		case key.Name == "down" || key.Name == "char" && strings.EqualFold(key.Char, "j"):
			pointing = true
			at = min(len(rows)-1, at+1)
		case key.Name == "pointer":
			mouse := key.Mouse
			if mouse.Button&64 != 0 {
				pointing = true
				at = max(0, min(len(rows)-1, at+mouse.Notches))
			} else if row, _, hit := frame.Hit(mouse); hit {
				pointing = true
				at = row
				if mouse.Released && mouse.Button&3 == 0 {
					key.Name = "enter"
				}
			} else {
				pointing = false
			}
		case key.Name == "char" && key.Char == "p":
			said, carried := menuCompanyList(title, keyboard, painter)
			if !carried {
				return false
			}
			if answered() != nil { // left, answered again over what is on
				return false
			}
			lineup()
			note = said
		case key.Name == "char" && key.Char == "r":
			changed, err := seat.SaveAdvice(session, c.Selected, c.Takes(answer))
			if err != nil {
				note = config.PyError(err)
			} else {
				c.Selected = changed
				if session == "" {
					c.Models, _ = config.Models()
				}
				note = ""
			}
		}
		if key.Name == "enter" && at >= 0 && at < len(rows) {
			modelWhy(title, answer[roles[at]], rows[at], roles[at], keyboard, painter)
		}
	}
}
