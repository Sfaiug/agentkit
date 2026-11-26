package plan

import (
	"context"
	"strings"

	"agentkit/internal/config"
	"agentkit/internal/notify"
	"agentkit/internal/task"
)

// ServedLine is the open line a seat's task with those checks serves, Python's served_line: the
// first open line whose check is one of them, runs of space folded, else "" for none, however
// few are open.  It names the line by its link, `<what> · written <when>`.  Read under the seat's
// lock, as Python's open_lines reads it, so a rename never moves the plan out from under the read.
func ServedLine(name string, checks []string) (string, error) {
	var opened []string
	if err := notify.Held(context.Background(), name, func(current string) (err error) {
		opened, err = Open(current)
		return err
	}); err != nil {
		return "", err
	}
	wanted := map[string]bool{}
	for _, check := range checks {
		bare, _ := task.SplitOnce(check)
		wanted[folded(bare)] = true
	}
	for _, line := range opened {
		if written, _ := parse(line); wanted[folded(written.Check)] {
			return written.link(), nil
		}
	}
	return "", nil
}

// folded is a command with each run of space one space and none at its ends, as Python's
// `" ".join(text.split())` leaves it.
func folded(command string) string {
	return strings.Join(strings.FieldsFunc(command, config.Space), " ")
}
