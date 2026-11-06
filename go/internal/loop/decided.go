package loop

import (
	"errors"
	"io/fs"
	"os"
	"path/filepath"
	"strings"

	"agentkit/internal/task"
)

const decidedRule = "These were decided before the build: hand in no finding against an Accepted line and no missing-work finding for a Not wanted line. They set what counts as asked-for; a defect a command shows stays a finding."

// decidedSection is the task's `## Decided` lines as its reviewer is handed them, Python's
// decided_section, "" for none: read from the run's copy of the task alone, as the prompt's body
// also carries the repository's rules, whose own `## Decided` is prose.
func decidedSection(dir string) (string, error) {
	data, err := os.ReadFile(filepath.Join(dir, "task.md"))
	if errors.Is(err, fs.ErrNotExist) {
		return "", nil
	} else if err != nil {
		return "", err
	}
	lines, err := task.Decided(task.Body(task.Text(data)))
	if err != nil || len(lines) == 0 {
		return "", err
	}
	return "## Decided before the build\n" + decidedRule + "\n\n" + strings.Join(lines, "\n") + "\n\n", nil
}
