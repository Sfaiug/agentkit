package plan

import (
	"strings"

	"agentkit/internal/config"
)

// Opened is whether the seat's plan, under the name it goes by now, has an open line `ak plan`
// wrote, as Python's open_lines finds any: a line kept by hand counts for nothing.
func Opened(current string) (bool, error) {
	lines, err := Open(current)
	return len(lines) > 0, err
}

// Open is the seat's plan's open lines `ak plan` wrote, each whole, Python's open_lines.
func Open(current string) ([]string, error) {
	lines, err := read(current)
	var kept []string
	for _, line := range lines {
		if _, written := parse(line); written && open(line) {
			kept = append(kept, strings.TrimFunc(line, config.Space))
		}
	}
	return kept, err
}
