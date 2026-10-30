package cli

import (
	"context"
	"errors"
	"fmt"
	"io"
	"os"
	"os/signal"
	"strconv"
	"syscall"
	"unicode/utf8"

	"agentkit/internal/config"
	"agentkit/internal/plan"
	"agentkit/internal/terminal"
)

func init() { commands["plan"] = runPlan }

// runPlan adds a line to the seat's plan (`add`), puts another check on one (`check`), or
// lists the plan.
func runPlan(args []string, out, errOut io.Writer) int {
	// a number in digits ASCII lacks, as validatePlan let through, or a check Go cannot read: Python's
	if len(args) > 0 && args[0] == "check" && (!config.Digits(args[1]) || !utf8.ValidString(args[2])) {
		return notImplemented(errOut, "plan")
	}
	// a stop ends the check that runs and removes its checkout before ak exits
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()
	name, record, _ := config.CurrentSession() // validatePlan refused one it cannot read
	var err error
	if len(args) == 0 {
		err = listPlan(ctx, name, out)
	} else {
		var line string
		if args[0] == "add" {
			repo, _ := record["repo"].(string) // validatePlan refused a seat filed under no project
			line, err = plan.Add(ctx, name, repo, args[1], args[3])
		} else {
			line, err = plan.Check(ctx, name, args[1], args[2])
		}
		if err == nil {
			fmt.Fprintln(out, line)
		}
	}
	if ctx.Err() != nil {
		return 128 + int(syscall.SIGTERM)
	}
	if errors.Is(err, plan.ErrUnread) {
		return notImplemented(errOut, "plan")
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
