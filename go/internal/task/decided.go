package task

import (
	"errors"
	"fmt"
	"strings"

	"agentkit/internal/commandhelp"
	"agentkit/internal/config"
)

// Decided is the lines of a task body's one `## Decided` section, in order, Python's decided, or
// the sentence a task cannot launch with: a second such section, or a line that starts with
// neither `Not wanted:` nor `Accepted:`.
func Decided(body string) ([]string, error) {
	found := sections(body, "Decided")
	if len(found) > 1 {
		return nil, errors.New("`## Decided` may appear only once; keep decisions in one section")
	}
	var lines []string
	for _, section := range found {
		for _, line := range config.SplitLines(section) {
			if line = strings.TrimFunc(line, config.Space); line == "" {
				continue
			}
			if !strings.HasPrefix(line, "Not wanted:") && !strings.HasPrefix(line, "Accepted:") {
				return nil, fmt.Errorf("`## Decided` lines must start with `Not wanted:` or `Accepted:`; got %s", commandhelp.Quote(line))
			}
			lines = append(lines, line)
		}
	}
	return lines, nil
}
