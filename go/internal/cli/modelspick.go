package cli

import (
	"maps"
	"slices"

	"agentkit/internal/config"
	"agentkit/internal/matrix"
	"agentkit/internal/menu"
	"agentkit/internal/quality"
	"agentkit/internal/seat"
	"agentkit/internal/terminal"
)

func modelsPick(title string, lineup []quality.Row, keyboard *terminal.Keyboard, painter *terminal.Painter) bool {
	at, top, find, note := 0, 0, "", ""
	current := map[string]bool{}
	for _, row := range lineup {
		current[row.Release] = true
	}
	defer painter.Forget()
	for {
		marks, err := matrix.Compared(lineup)
		if err != nil {
			return false
		}
		s := keyboard.Screen()
		rows := menu.CompareLines(s, lineup, marks, find)
		choices := []int{0}
		for i, row := range rows {
			if row.Release != "" {
				choices = append(choices, i)
			}
		}
		at = min(at, len(choices)-1)
		frame := menu.CompareFrame(s, title, rows, marks, len(current), find, choices[at], top, note)
		top = frame.Top
		painter.Write(frame.Lines, s)
		key := keyboard.ReadKey()
		note = ""
		switch key.Name {
		case "esc", "eof":
			return true
		case "again":
			painter.Forget()
		case "up":
			at = max(0, at-1)
		case "down":
			at = min(len(choices)-1, at+1)
		case "char", "backspace":
			if key.Name == "char" {
				find += key.Char
			} else if text := []rune(find); len(text) > 0 {
				find = string(text[:len(text)-1])
			}
			at, top = 1, 0
		case "pointer":
			mouse := key.Mouse
			if mouse.Button&64 != 0 {
				at = max(0, min(len(choices)-1, at+mouse.Notches))
			} else if row, column, hit := frame.Hit(mouse); hit && column >= 0 {
				at = slices.Index(choices, row)
				if mouse.Released && mouse.Button&3 == 0 {
					key.Name = "space"
				}
			}
		}
		if key.Name == "space" {
			changed := maps.Clone(marks)
			if changed == nil || at == 0 {
				changed = map[string]bool{}
			}
			if at > 0 {
				slug := rows[choices[at]].Release
				if changed[slug] {
					delete(changed, slug)
				} else {
					changed[slug] = true
				}
			}
			if err := config.RememberCompare(slices.Sorted(maps.Keys(changed)), seat.KeepConfigEfforts); err != nil {
				note = config.PyError(err)
			}
		}
	}
}
