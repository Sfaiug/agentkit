package cli

import (
	"fmt"
	"io"
	"os"
	"os/exec"
	"time"

	"agentkit/internal/config"
	"agentkit/internal/host"
	"agentkit/internal/menu"
	"agentkit/internal/seat"
	"agentkit/internal/terminal"
)

func menuStop(shown *reading, dry bool, keyboard *terminal.Keyboard, painter *terminal.Painter, highlight *menu.Highlight, errOut io.Writer) (bool, int) {
	name, _, err := config.CurrentSession()
	count, known := seat.StopCount(name, time.Now())
	found, done := ownSeat(shown.seats, name)
	if err != nil || !known || !found {
		keyboard.Give()
		return true, notImplemented(errOut, "attach")
	}
	*highlight = menu.Highlight{Cursor: name}
	what := "No runs stop"
	if count == 1 {
		what = "1 run stops"
	} else if count > 1 {
		what = fmt.Sprintf("%d runs stop", count)
	}
	meaning := what + " with it; the session moves to past sessions, p, where it reopens where it stopped."
	accepted := done
	if !done {
		accepted, known = confirmMenu(keyboard, painter, name, "Stop "+name+" and everything it runs?", meaning, "Stop", func(screen terminal.Screen) menu.Frame {
			return menu.Draw(menu.View{Screen: screen, Seats: shown.seats, Cells: shown.cells, Standing: shown.standing,
				Clock: time.Now().Format("15:04"), Highlight: menu.Highlight{Cursor: name, Hidden: true}, Switches: shown.switches}, screen.Width(), screen.Height())
		})
	}
	if !known {
		keyboard.Give()
		return true, notImplemented(errOut, "attach")
	}
	if !accepted {
		return false, 0
	}
	if !dry {
		if err := runMenuStop(name); err != nil {
			keyboard.Give()
			fmt.Fprintf(errOut, "ak attach: stop: %v\n", err)
			return true, 1
		}
	}
	keyboard.Give()
	return true, 0
}

// The popup leaves as soon as the existing stop starts. Its own session and streams let the
// stop finish after tmux closes the popup and its seat, without holding that terminal open.
func runMenuStop(name string) error {
	self, err := os.Executable()
	if err != nil {
		return err
	}
	stop := exec.Command(self, "orch", "stop", name)
	stop.Env = host.Unmarked(os.Environ())
	host.Detach(stop)
	if err := stop.Start(); err != nil {
		return err
	}
	go stop.Wait()
	return nil
}
