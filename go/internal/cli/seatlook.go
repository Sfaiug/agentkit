package cli

import (
	"io"
	"os"
	"strconv"

	"agentkit/internal/host"
	"agentkit/internal/seat"
)

// seatLook is the look a seat's wrapper starts, `ak seat-look <seat> <pane's pid>` as it ends and
// with no pid when the screen shows news, and its prompt hook with the moment it heard the owner's
// words after them, those words on its stdin; and with the seat alone, a run's redress of its bar
// (seat.Redress).  Unlisted as `adapter` and `hook` are: nothing reads what it says.
func seatLook(args []string) int {
	if len(args) < 1 || len(args) > 3 {
		return 0
	}
	host.Mark("seat look")
	if len(args) == 1 {
		seat.Publish(args[0])
		return 0
	}
	var heard *seat.Prompt
	if len(args) == 3 {
		at, err := strconv.ParseFloat(args[2], 64)
		said, read := io.ReadAll(os.Stdin)
		if err != nil || read != nil {
			return 0
		}
		heard = &seat.Prompt{At: at, Said: string(said)}
	}
	seat.Look(args[0], args[1], heard)
	return 0
}
