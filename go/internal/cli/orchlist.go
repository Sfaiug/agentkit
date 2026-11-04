package cli

import (
	"errors"
	"fmt"
	"io"
	"time"

	"agentkit/internal/host"
	listings "agentkit/internal/listing"
	"agentkit/internal/seat"
	"agentkit/internal/terminal"
)

func init() { commands["orch list"] = orchList }

// orchList draws the seats Go knows, or with none says how to open one; then where the agents
// run. Its explanations use the same observation that decided each row and its bar.
func orchList(args []string, out, errOut io.Writer) int {
	now := time.Now()
	home, known := seat.Looking(now)
	screen := terminal.For(out)
	if !known {
		return notImplemented(errOut, "orch list")
	}
	if err := home.Announce(now); errors.Is(err, seat.ErrUnread) {
		return notImplemented(errOut, "orch list")
	} else if err != nil {
		fmt.Fprintf(errOut, "ak orch: %v\n", err)
		return 1
	}
	lines := listings.Seats(screen, home.Seats, now, len(args) > 0)
	for _, line := range lines {
		fmt.Fprintln(out, line)
	}
	for _, line := range terminal.Wrap(host.SliceLine(), screen.ContentWidth()) {
		fmt.Fprintln(out, terminal.Dim(out, line))
	}
	for _, each := range home.Seats {
		if each.Warning != "" {
			fmt.Fprintln(errOut, "WARN "+each.Warning)
		}
	}
	return 0
}
