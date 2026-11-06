package cli

import (
	"time"

	"agentkit/internal/menu"
	"agentkit/internal/terminal"
)

// menuMeter is a click on a subscription's meter on the ak screen (menu.meter_acts): what it offers
// (Cell.Acts, nothing removed from here) picked from a list under its name, lit on `log in again`
// where offered and otherwise on nothing, so a reset is spent only by a move or a click there.  One
// that offers nothing opens no list, the pointer still on it; once a list was up, its keys had the
// highlight, so main's pointer is let go.  false where the act picked is Python's, nothing written:
// a reset spent.
func menuMeter(cell menu.Cell, main *menu.Highlight, keyboard *terminal.Keyboard, painter *terminal.Painter) bool {
	acts := cell.Acts(false)
	if len(acts) == 0 {
		return true
	}
	defer painter.Forget()
	main.Pointer = terminal.Mouse{}
	highlight := menu.Highlight{Cursor: menu.LogInAgain}
	for {
		screen := keyboard.Screen()
		frame := menu.ActsFrame(screen, cell.Label, time.Now().Format("15:04"), acts, highlight)
		painter.Write(frame.Lines, screen)
		key := keyboard.ReadKey()
		switch act := frame.Open(key); {
		case act == menu.LogInAgain:
			signIn(cell, keyboard, painter) // one that did not finish said so before the menu came back
			return true
		case act != "":
			return false
		case highlight.Move(key, frame):
		case key.Name == "esc" || key.Name == "eof":
			return true
		case key.Name == "again":
			painter.Forget()
		}
	}
}
