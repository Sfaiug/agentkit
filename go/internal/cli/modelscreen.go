package cli

import (
	"fmt"
	"slices"
	"strings"
	"sync"
	"time"

	"agentkit/internal/config"
	"agentkit/internal/matrix"
	"agentkit/internal/menu"
	"agentkit/internal/quality"
	"agentkit/internal/seat"
	"agentkit/internal/terminal"
)

var readingModels sync.Mutex // closing and reopening the page shares the boards' reader

func menuModels(session, scope string, c *matrix.Configuration, keyboard *terminal.Keyboard, painter *terminal.Painter) bool {
	type reading struct {
		found *matrix.Matrix
		err   error
	}
	read := make(chan reading, 1)
	go func() {
		readingModels.Lock()
		defer readingModels.Unlock()
		found, err := matrix.Refresh(false)
		read <- reading{found, err}
		keyboard.Wake()
	}()
	found := matrix.Stored()
	compared, err := matrix.Compared(found.Rows)
	if err != nil {
		return false
	}
	answer := quality.Answer(found.Rows, compared)
	var rows []*quality.Rating
	var roles []string
	at, top, note := -1, 0, ""
	lineup := func() {
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
			if fresh.err != nil {
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
		frame := menu.ModelsFrame(s, "config · recommended · "+scope, menu.ModelsSaid(s, answer, found.Rows),
			compared, len(current), found.Fetched, at, top, note)
		top = frame.Top
		painter.Write(frame.Lines, s)
		key := keyboard.ReadKey()
		switch {
		case key.Name == "esc" || key.Name == "eof":
			return true
		case key.Name == "again":
			painter.Forget()
		case key.Name == "up" || key.Name == "char" && strings.EqualFold(key.Char, "k"):
			at = max(0, at-1)
		case key.Name == "down" || key.Name == "char" && strings.EqualFold(key.Char, "j"):
			at = min(len(rows)-1, at+1)
		case key.Name == "pointer":
			mouse := key.Mouse
			if mouse.Button&64 != 0 {
				step := -1
				if mouse.Button&1 != 0 {
					step = 1
				}
				at = max(0, min(len(rows)-1, at+step))
			} else if row, _, hit := frame.Hit(mouse); hit {
				at = row
				if mouse.Released && mouse.Button&3 == 0 {
					key.Name = "enter"
				}
			}
		case key.Name == "char" && key.Char == "p":
			return false // choosing the compared releases follows in models_pick
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
			modelWhy(rows[at], roles[at], keyboard, painter)
		}
	}
}

// The row's explanation opens without changing the answer or its pointer.
func modelWhy(row *quality.Rating, role string, keyboard *terminal.Keyboard, painter *terminal.Painter) {
	does := map[string]string{"orchestrate": "orchestrates", "execute": "builds", "review": "reviews"}
	parts := []string{"why", row.Name, row.Effort, does[role]}
	parts = slices.DeleteFunc(parts, func(part string) bool { return part == "" })
	defer painter.Forget()
	for {
		s := keyboard.Screen()
		var body []string
		for _, text := range []string{strings.Join(parts, " "), fmt.Sprintf("quality %.1f ± %.1f   $%.2f a task", row.Quality, row.SE, *row.Cost)} {
			for _, line := range terminal.Wrap(text, s.LayoutWidth()-2) {
				body = append(body, "  "+line)
			}
		}
		painter.Write(menu.Panel(s, "config · recommended", time.Now().Format("15:04"), body, "esc back"), s)
		key := keyboard.ReadKey()
		if key.Name == "esc" || key.Name == "eof" {
			return
		}
	}
}
