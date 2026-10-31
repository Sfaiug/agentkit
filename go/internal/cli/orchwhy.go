package cli

import (
	"fmt"
	"io"
	"time"

	"agentkit/internal/commandhelp"
	"agentkit/internal/config"
	"agentkit/internal/host"
	"agentkit/internal/seat"
)

func init() { commands["orch why"] = orchWhy }

// orchWhy explains a seat Go reads as Python's orch.cmd_why does, or refuses a name no seat
// answers to.
func orchWhy(args []string, out, errOut io.Writer) int {
	now := time.Now()
	home, known := seat.Read(now)
	name, _, err := config.ResolveSession(args[0])
	if !known || err != nil && !home.Seatless() {
		return notImplemented(errOut, "orch why")
	}
	lines, found, err := home.Explain(name, now)
	if err != nil {
		fmt.Fprintf(errOut, "ak orch: %v\n", err)
		return 1
	}
	if !found {
		fmt.Fprintf(errOut, "ak orch: no orchestrator session %s; `ak orch list` shows them\n", commandhelp.Quote(args[0]))
		return 2
	}
	for _, line := range lines {
		fmt.Fprintln(out, line)
	}
	// where there is no manager the seat's tmux server was started the way it always was, and
	// this is the one place that says so
	plainly := ""
	if !host.UserManager() {
		plainly = "; this seat's tmux server was started plainly"
	}
	fmt.Fprintln(out, "  slice:     "+host.SliceLine()+plainly)
	return 0
}
