package cli

import (
	"strings"
	"time"

	"agentkit/internal/config"
	"agentkit/internal/menu"
	"agentkit/internal/seat"
	"agentkit/internal/terminal"
)

// opening is the maintenance Python's menu.main runs as the screen opens, but on a dry run or the
// overlay: the seat sweep, and what it said, as orch.maintenance logs it.  False where Go leaves
// the sweep to Python.
func opening(none bool) ([]string, bool) {
	var said []string
	if none {
		return nil, true
	}
	carried, err := seat.Sweep(time.Now(), func(line string) { said = append(said, line) })
	if err != nil {
		said = append(said, "WARN could not check the sessions: "+config.PyError(err))
	}
	return said, carried
}

// menuNote shows what the opening said, as Python's menu.show_notices and pause do: a note in the
// menu's frame until Esc or Enter.  False where the keyboard ends, which leaves the screen.
func menuNote(said []string, keyboard *terminal.Keyboard, painter *terminal.Painter) bool {
	for len(said) > 0 {
		screen := keyboard.Screen()
		var body []string
		for _, line := range said {
			line = strings.ReplaceAll(line, config.UserHome()+"/", "~/")
			for _, part := range terminal.Wrap(line, max(1, screen.LayoutWidth()-2)) {
				body = append(body, "  "+part)
			}
		}
		painter.Write(menu.Panel(screen, "note", time.Now().Format("15:04"), body, "esc back"), screen)
		switch key := keyboard.ReadKey(); key.Name {
		case "esc", "enter":
			return true
		case "eof":
			return false
		case "again":
			painter.Forget()
		}
	}
	return true
}
