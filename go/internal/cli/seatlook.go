package cli

import (
	"agentkit/internal/host"
	"agentkit/internal/seat"
)

// seatLook is the look a seat's wrapper starts, `ak seat-look <seat> <pane's pid>` as it ends and
// with no pid when the screen shows news, unlisted as `adapter` and `hook` are: nothing reads what
// it says.
func seatLook(args []string) int {
	if len(args) == 2 {
		host.Mark("seat look")
		seat.Look(args[0], args[1])
	}
	return 0
}
