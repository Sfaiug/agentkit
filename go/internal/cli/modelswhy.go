package cli

import (
	"strings"
	"time"

	"agentkit/internal/menu"
	"agentkit/internal/quality"
	"agentkit/internal/terminal"
)

// The row's explanation opens without changing the answer or its pointer.
func modelWhy(title string, found *quality.Said, row *quality.Rating, role string, keyboard *terminal.Keyboard, painter *terminal.Painter) {
	defer painter.Forget()
	top := 0
	for {
		s := keyboard.Screen()
		body := menu.ModelsWhy(s, found, role, row)
		clock := time.Now().Format("15:04")
		room := max(1, s.Height()-len(menu.Panel(s, title, clock, nil, "esc back"))-1)
		top = max(0, min(top, len(body)-room))
		painter.Write(menu.Panel(s, title, clock, body[top:min(top+room, len(body))], "esc back"), s)
		key := keyboard.ReadKey()
		switch {
		case key.Name == "esc" || key.Name == "eof":
			return
		case key.Name == "again":
			painter.Forget()
		case key.Name == "up" || key.Name == "char" && strings.EqualFold(key.Char, "k"):
			top -= room
		case key.Name == "down" || key.Name == "char" && strings.EqualFold(key.Char, "j"):
			top += room
		case key.Name == "pointer" && key.Mouse.Button&64 != 0:
			if key.Mouse.Notches < 0 {
				top -= room
			} else {
				top += room
			}
		}
	}
}
