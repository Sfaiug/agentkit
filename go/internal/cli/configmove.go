package cli

import (
	"agentkit/internal/config"
	"agentkit/internal/menu"
	"agentkit/internal/seat"
	"agentkit/internal/terminal"
)

func moveConfigSeat(name string, view *menu.ConfigView, keyboard *terminal.Keyboard, painter *terminal.Painter) bool {
	model := view.Matrix.Names[view.Row]
	card := cardOn(name, view, keyboard, painter)
	known, err := seat.Move(name, model, "", func(kept bool) (bool, bool) {
		return card("Restart "+name+" on "+config.ModelName(model, view.Matrix.Models)+"?", "Move", kept)
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
