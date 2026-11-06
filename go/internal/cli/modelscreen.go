package cli

import (
	"errors"
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

// title is the name `c` gives this page; the pages it opens, `p` and a row's why, carry it too.
func menuModels(session, title string, c *matrix.Configuration, keyboard *terminal.Keyboard, painter *terminal.Painter) bool {
	type reading struct {
		found *matrix.Matrix
		err   error
	}
	found := matrix.Stored()
	compared, err := matrix.Compared(found.Rows)
	if priced, failed := matrix.Priced(found.Rows); err != nil || failed != nil || priced {
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
	answer := quality.Answer(found.Rows, compared)
	var rows []*quality.Rating
	var roles []string
	var colours map[string]string
	pointing := false
	at, top, note := -1, 0, ""
	lineup := func() {
		colours = modelColours(found.Rows)
		rows, roles = nil, nil
		at = -1
		for _, role := range quality.Roles {
			for _, row := range answer[role].Front {
				if at < 0 && row == answer[role].Pick {
					at = len(rows)
				}
				rows, roles = append(rows, row), append(roles, role)
			}
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
			if errors.Is(fresh.err, matrix.ErrPriced) {
				return false
			} else if fresh.err != nil {
				note = "the boards were not read: " + fresh.err.Error()
			} else {
				found = fresh.found
				if compared, err = matrix.Compared(found.Rows); err != nil {
					return false
				}
				answer = quality.Answer(found.Rows, compared)
				lineup()
			}
		default:
		}
		current := map[string]bool{}
		for _, row := range found.Rows {
			current[row.Release] = true
		}
		s := keyboard.Screen()
		light := menu.ModelLight{}
		if pointing && at >= 0 && at < len(rows) {
			light = menu.ModelLight{Maker: rows[at].Maker, Colour: colours[rows[at].Maker]}
		}
		frame := menu.ModelsFrame(s, title, menu.ModelsSaid(s, answer, found.Rows),
			compared, len(current), found.Fetched, at, top, note, light)
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
			if !modelsPick(title, found.Rows, keyboard, painter) {
				return false
			}
			if compared, err = matrix.Compared(found.Rows); err != nil {
				return false
			}
			answer = quality.Answer(found.Rows, compared)
			lineup()
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
