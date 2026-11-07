package plan

import (
	"context"
	"strings"

	"agentkit/internal/notify"
)

// Planned is what the open lines `ak plan` wrote in the seat's plan set out to do, one to a line,
// as Python's retire.planned reads them: none from a plan nothing can read.
func Planned(name string) string {
	var what []string
	notify.Held(context.Background(), name, func(current string) error {
		lines, err := Open(current)
		for _, line := range lines {
			entry, _ := parse(line)
			what = append(what, entry.What)
		}
		return err
	})
	return strings.Join(what, "\n")
}
