package cli

import (
	"agentkit/internal/host"
	"agentkit/internal/seat"
)

// seatLook is the look a seat's wrapper starts as it ends, `ak seat-look <seat> <pane's pid>`,
// unlisted as `adapter` and `hook` are: nothing waits on it and nothing reads what it says.
func seatLook(args []string) int {
	if len(args) == 2 {
		host.Mark("seat look")
		seat.Look(args[0], args[1])
	}
	return 0
}
