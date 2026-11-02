package plan

import (
	"strings"

	"agentkit/internal/config"
)

// OpenLines is the seat's open lines without their boxes, as orch.in_flight tells another seat of
// them: all of a seat filed where it asks, else only those written on a checkout `here` says is
// that one.  A plan that cannot be read, or a line's path place cannot read as Python does, is an
// error: its lines would go untold.
func OpenLines(name string, filed bool, here func(repo string) bool) ([]string, error) {
	lines, err := read(name)
	if err != nil {
		return nil, err
	}
	var env, kept []string
	for _, line := range lines {
		if !open(line) {
			continue
		}
		if !filed {
			written, ok := parse(line)
			if !ok {
				continue
			}
			if !pythonPath(written.Project) {
				return nil, ErrUnread
			}
			if env == nil {
				if env, err = environ(); err != nil {
					return nil, err
				}
			}
			if repo, _ := place(written.Project, env); !here(repo) {
				continue
			}
		}
		line = strings.TrimFunc(line, config.Space)
		kept = append(kept, strings.TrimFunc(line[boxLine.FindStringIndex(line)[1]:], config.Space))
	}
	return kept, nil
}
