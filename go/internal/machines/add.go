package machines

import (
	"context"
	"fmt"
	"slices"
	"time"

	"agentkit/internal/config"
	"agentkit/internal/gitcall"
	"agentkit/internal/host"
	"agentkit/internal/run"
)

// Ask asks name, an ssh address, once as Check asks each machine, and records an answer as its
// first check, both until ctx ends: "" for Add to write it, else why not (Python's
// machines.add).  One ak may use already is not asked.
func Ask(ctx context.Context, name string) string {
	if names, _ := known(); slices.Contains(names, name) {
		return name + " is a machine already"
	}
	now := float64(time.Now().UnixNano()) / 1e9
	// typing it answers the question ssh would ask of a host key it has not seen: that one is
	// learned, and one it knows otherwise still refused
	answer := answers(ctx, []string{name}, "-o", "StrictHostKeyChecking=accept-new")[0]
	said := said(answer.Out)
	if said == nil && answer.Said == nil {
		return fmt.Sprintf("%s did not answer in %d seconds", name, host.Within)
	}
	if said == nil {
		why := name + " did not answer"
		if lines := config.SplitLines(gitcall.Strip(text(answer.Said))); len(lines) > 0 {
			why += ": " + lines[len(lines)-1] // ssh's own, or the probe's
		}
		return why
	}
	said.Set("at", now)
	entry := run.NewObject()
	entry.Set("checks", []any{[]any{run.Float(now), true}})
	entry.Set("said", said)
	if err := write(ctx, func(record *run.Object) { record.Set(name, entry) }); err != nil {
		return fmt.Sprintf("%s answered, but its answer could not be recorded: %s", name, config.PyError(err))
	}
	return ""
}

// Add writes name's `[machines.<name>]`, nothing in it, keep as Save's: a machine ak may use.
func Add(name string, keep func() error) error {
	implied, err := implied()
	if err != nil {
		return err
	}
	return config.AddMachine(name, implied, keep)
}
