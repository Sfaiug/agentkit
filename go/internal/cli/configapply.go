package cli

import (
	"fmt"
	"strings"

	"agentkit/internal/config"
	"agentkit/internal/menu"
	"agentkit/internal/seat"
	"agentkit/internal/terminal"
)

// applyDefaults is `a` on a fresh window's `c` (menu.apply_defaults): a card asks how many of the
// main screen's seats the defaults change and which of them restart, Keep or Esc leaves every
// record as it was, and `Apply` gives them the defaults (seat.Defaults.Apply), saying under the
// rows each seat that refused. False hands the key over: whatever Go cannot tell or carry.
func applyDefaults(view *menu.ConfigView, main func() *reading, keyboard *terminal.Keyboard, painter *terminal.Painter) bool {
	shown := main()
	if shown.handoff {
		return false
	}
	rows := make([]string, len(shown.seats))
	for i, row := range shown.seats {
		rows[i] = row.Name
	}
	models, lead := view.Matrix.Models, view.Matrix.Selected.Str("orchestrator")
	given, known := seat.DefaultsMove(rows, lead)
	if !known {
		return false
	}
	open, restarts := given.Open, given.Restarts
	if len(open) == 0 {
		view.Note = "no session to apply them to"
		return true
	}
	sessions, restart, means := "sessions", "restart", "No session restarts."
	if len(open) == 1 {
		sessions = "session"
	}
	if len(restarts) == 1 {
		restart = "restarts"
	}
	if len(restarts) > 0 {
		means = fmt.Sprintf("%s %s on %s at %s.", strings.Join(restarts, ", "), restart,
			config.ModelName(lead, models), models[lead].Efforts["effort"])
	}
	ask := fmt.Sprintf("Give new seats' models and efforts to %d %s?", len(open), sessions)
	const spot = "apply" // the matrix's last row, where the card goes, with the highlighted one kept
	accepted, known := confirmMenu(keyboard, painter, spot, ask, means, "Apply", func(screen terminal.Screen) menu.Frame {
		return menu.ConfigMoveFrame(screen, *view, spot)
	})
	if !known || !accepted {
		return known
	}
	view.Note, known = given.Apply()
	return known
}
