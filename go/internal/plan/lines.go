package plan

import (
	"strings"

	"agentkit/internal/config"
)

// Lines is the seat's plan's lines, as Python's plan.lines reads them: none without a plan, and an
// error where it has one nothing can read.
func Lines(current string) ([]string, error) { return read(current) }

// Checked is each box line of the plan's lines as a done check's fingerprint holds it
// (done_check.fingerprint): stripped, and a line `ak plan` wrote without the done field a
// renewed proof changes, so only what the plan says counts.
func Checked(lines []string) []string {
	var checked []string
	for _, line := range lines {
		if !boxed(line) {
			continue
		}
		line = strings.TrimFunc(line, config.Space)
		if entry, ok := parse(line); ok {
			line = line[:len("- [ ] ")] + entry.bare // plan.undone
		}
		checked = append(checked, line)
	}
	return checked
}
