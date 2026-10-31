package cli

import (
	"fmt"
	"io"
	"time"

	"agentkit/internal/commandhelp"
	"agentkit/internal/seat"
)

func init() { commands["orch why"] = orchWhy }

// orchWhy refuses the name where no seat exists; explaining a seat comes with the seats.
func orchWhy(args []string, _, errOut io.Writer) int {
	if home, known := seat.Read(time.Now()); !known || !home.Seatless() {
		return notImplemented(errOut, "orch why")
	}
	fmt.Fprintf(errOut, "ak orch: no orchestrator session %s; `ak orch list` shows them\n", commandhelp.Quote(args[0]))
	return 2
}
