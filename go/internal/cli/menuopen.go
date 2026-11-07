package cli

import (
	"fmt"
	"io"
	"os"
	"strconv"
	"strings"

	"agentkit/internal/menu"
	"agentkit/internal/seat"
	"agentkit/internal/terminal"
)

func menuChoice(key terminal.Key, frame menu.Frame, seats []menu.Seat, keyboard *terminal.Keyboard) string {
	if key.Name == "char" && len(key.Char) == 1 && key.Char[0] >= '0' && key.Char[0] <= '9' {
		number, _ := strconv.Atoi(keyboard.Number(key.Char, len(seats)))
		if number > 0 && number <= len(seats) {
			return seats[number-1].Name
		}
	}
	return frame.Open(key)
}

func menuKeys(screen terminal.Screen, shown *reading, own string) string {
	keys := menu.Keys(screen, len(shown.past) > 0)
	if found, done := ownSeat(shown.seats, own); found {
		x := "x stop   "
		if done {
			x = "x close   "
		}
		keys = strings.Replace(keys, "n new   ", "n new   "+x, 1)
	}
	return keys
}

func openMenuSeat(name string, dry, overlay bool, keyboard *terminal.Keyboard, painter *terminal.Painter, errOut io.Writer) (leave bool, code int) {
	keyboard.Give()
	known, err := seat.Visit(name, dry, os.Stdout, errOut)
	if !known {
		return true, notImplemented(errOut, "attach")
	}
	if err != nil {
		fmt.Fprintf(errOut, "ak attach: %s\n", err)
	}
	if overlay {
		return true, 0
	}
	keyboard.Take()
	painter.Forget()
	return false, 0
}
