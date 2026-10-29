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

func init() { commands["plan"] = runPlan }

// runPlan adds a line to the seat's plan (`add`), or lists the plan.
func runPlan(args []string, out, errOut io.Writer) int {
	if len(args) > 0 && args[0] != "add" {
		return notImplemented(errOut, "plan") // `plan check` comes in a later milestone
	}
	// a stop ends the check that runs and removes its checkout before ak exits
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()
	name, record, _ := config.CurrentSession() // validatePlan refused one it cannot read
	var err error
	if len(args) > 0 {
		repo, _ := record["repo"].(string) // validatePlan refused a seat filed under no project
		var line string
		if line, err = plan.Add(ctx, name, repo, args[1], args[3]); err == nil {
			fmt.Fprintln(out, line)
		}
	} else {
		err = listPlan(ctx, name, out)
	}
	if ctx.Err() != nil {
		return 128 + int(syscall.SIGTERM)
	}
	if err != nil {
		fmt.Fprintf(errOut, "ak plan: %s\n", err)
		return 2
	}
	return 0
}

// listPlan ticks what landed, then lists every box line, numbered and wrapped to the terminal.
func listPlan(ctx context.Context, name string, out io.Writer) error {
	listed, err := plan.List(ctx, name)
	if err != nil {
		return err
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
	return nil
}
