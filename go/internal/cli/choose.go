package cli

import (
	"time"

	"agentkit/internal/menu"
	"agentkit/internal/terminal"
)

// menuChoose is one of the list's choices picked with the keys (terminal.choose), the list laid out
// again for each draw and the highlight starting on cursor: ↑/↓, k/j and the wheel move it, the
// pointer lights the choice under it, and Enter or a click picks one; "" on Esc.
func menuChoose(list func(terminal.Screen) menu.List, cursor string, keyboard *terminal.Keyboard, painter *terminal.Painter) string {
	highlight := menu.Highlight{Cursor: cursor}
	for {
		screen := keyboard.Screen()
		shown := list(screen)
		shown.Clock = time.Now().Format("15:04")
		frame := shown.Frame(screen, highlight)
		painter.Write(frame.Lines, screen)
		key := keyboard.ReadKey()
		if choice := frame.Open(key); choice != "" {
			return choice
		}
		switch {
		case highlight.Move(key, frame):
		case key.Name == "esc" || key.Name == "eof":
			return ""
		case key.Name == "again":
			painter.Forget()
		}
	}
}
