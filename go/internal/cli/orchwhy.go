package cli

import (
	"fmt"
	"io"

	"agentkit/internal/commandhelp"
)

func init() { commands["orch why"] = orchWhy }

// orchWhy refuses the name where no seat exists; explaining a seat comes with the seats.
func orchWhy(args []string, _, errOut io.Writer) int {
	if !seatless() {
		return notImplemented(errOut, "orch why")
	}
	fmt.Fprintf(errOut, "ak orch: no orchestrator session %s; `ak orch list` shows them\n", commandhelp.Quote(args[0]))
	return 2
}
