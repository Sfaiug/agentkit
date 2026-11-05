package cli

import (
	"strings"
	"time"

	"agentkit/internal/config"
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

// menuNote shows what the opening said as Python's menu.show_notices does with the keyboard given
// back: each line under the last, then `esc back`, until Esc or Enter.  False where the keyboard
// ends, which leaves the screen.
func menuNote(said []string, keyboard *terminal.Keyboard, painter *terminal.Painter) bool {
	for len(said) > 0 {
		screen := keyboard.Screen()
		var lines []string
		for _, line := range said {
			for _, part := range terminal.Wrap(strings.ReplaceAll(line, config.UserHome()+"/", "~/"), max(1, screen.Width()-1)) {
				lines = append(lines, " "+part)
			}
		}
		painter.Write(append(lines, "esc back"), screen)
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
