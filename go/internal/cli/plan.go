package cli

import (
	"context"
	"fmt"
	"io"
	"os"
	"os/signal"
	"strconv"
	"syscall"

	"agentkit/internal/config"
	"agentkit/internal/plan"
	"agentkit/internal/terminal"
)

func init() { commands["plan"] = listPlan }

// listPlan ticks what landed, then lists every box line, numbered and wrapped to the terminal.
func listPlan(args []string, out, errOut io.Writer) int {
	if len(args) > 0 {
		return notImplemented(errOut, "plan") // `plan add` and `plan check` come in a later milestone
	}
	// a stop ends the check that runs and removes its checkout before ak exits
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()
	name, _, _ := config.CurrentSession() // validatePlan refused one it cannot read
	listed, err := plan.List(ctx, name)
	if ctx.Err() != nil {
		return 128 + int(syscall.SIGTERM)
	}
	if err != nil {
		fmt.Fprintf(errOut, "ak plan: %s\n", err)
		return 2
	}
	width := max(2, len(strconv.Itoa(len(listed))))
	room := max(1, terminal.For(out).Width()-width-2)
	for n, line := range listed {
		wrapped := terminal.Wrap(line, room)
		fmt.Fprintf(out, "%*d  %s\n", width, n+1, wrapped[0])
		for _, more := range wrapped[1:] {
			fmt.Fprintf(out, "%*s%s\n", width+2, "", more)
		}
	}
	return 0
}
