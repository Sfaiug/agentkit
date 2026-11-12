package cli

import (
	"agentkit/internal/menu"
	"agentkit/internal/terminal"
)

// moveMeans is what a seat's restart card says of its conversation, kept or not (menu.MOVE_MEANS).
var moveMeans = map[bool]string{true: "It keeps its conversation.", false: "It starts a new conversation, handed the one it had."}

// A seatCard asks `question` on the card under a seat's row of `c`, `action` restarting it, and
// says whether its conversation goes on (seat.Move's `kept`); not known where the screen ended.
type seatCard func(question, action string, kept bool) (accepted, known bool)

// cardOn is the seat's card over `view` as it stands when asked (terminal.confirm).
func cardOn(name string, view *menu.ConfigView, keyboard *terminal.Keyboard, painter *terminal.Painter) seatCard {
	return func(question, action string, kept bool) (bool, bool) {
		return confirmMenu(keyboard, painter, name, question, moveMeans[kept], action, func(screen terminal.Screen) menu.Frame {
			return menu.ConfigMoveFrame(screen, *view, name)
		})
	}
}
