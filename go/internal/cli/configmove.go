package cli

import (
	"agentkit/internal/config"
	"agentkit/internal/menu"
	"agentkit/internal/seat"
	"agentkit/internal/terminal"
)

func moveConfigSeat(name string, view *menu.ConfigView, keyboard *terminal.Keyboard, painter *terminal.Painter) bool {
	model := view.Matrix.Names[view.Row]
	known, err := seat.Move(name, model, "", func() (bool, bool) {
		return confirmMenu(keyboard, painter, name, "Restart "+name+" on "+config.ModelName(model, view.Matrix.Models)+"?",
			"It starts a new conversation, handed the one it had.", "Move", func(screen terminal.Screen) menu.Frame {
				return menu.ConfigMoveFrame(screen, *view, name)
			})
	})
	if err != nil {
		view.Note = config.Fold(err.Error())
	} else if known {
		if selected, err := seat.ConfigSelection(name); err == nil && selected != nil {
			view.Matrix.Selected = selected
		}
	}
	return known
}
