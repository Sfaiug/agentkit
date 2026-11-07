package cli

import (
	"io"
	"strconv"

	"agentkit/internal/seat"
)

// orchEnded is tmux's pane-died hook, `ak orch ended NAME WHEN` (seat.Ended): WHEN is the moment
// the seat's harness ended, by tmux's clock.
func orchEnded(args []string, out, errOut io.Writer) int {
	if len(args) == 2 {
		if died, err := strconv.ParseFloat(args[1], 64); err == nil {
			known, err := seat.Ended(args[0], died, out)
			return orchAnswer("orch", "", known, err, out, errOut)
		}
	}
	return orchAnswer("orch", "", true, seat.Refusal("usage: ak orch ended NAME WHEN"), out, errOut)
}
