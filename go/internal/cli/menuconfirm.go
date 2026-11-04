package cli

import (
	"agentkit/internal/menu"
	"agentkit/internal/terminal"
)

func confirmMenu(keyboard *terminal.Keyboard, painter *terminal.Painter, name, question, meaning, action string, draw func(terminal.Screen) menu.Frame) bool {
	highlight := menu.Highlight{Cursor: "Keep"}
	for {
		screen := keyboard.Screen()
		frame := draw(screen).Confirm(screen, name, question, meaning, action, highlight)
		if len(frame.Lines) == 0 {
			return false
		}
		painter.Write(frame.Lines, screen)
		key := keyboard.ReadKey()
		if choice := frame.Open(key); choice != "" {
			return choice == action
		}
		switch {
		case highlight.Move(key, frame):
		case key.Name == "esc" || key.Name == "eof":
			return false
		case key.Name == "again":
			painter.Forget()
		}
	}
}
