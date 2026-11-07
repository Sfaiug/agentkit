package loop

import (
	"agentkit/internal/config"
	"agentkit/internal/run"
)

// doneChecks is a scratch builder's turn held to the task's own checks, as Python's turn checks
// hold it: with `scratch` set and no base, its hand-in has no change to count, scope or rule.
func (s scratch) doneChecks(l *loop, _ string) *run.Object {
	files := []any{}
	for _, spec := range s.files {
		files = append(files, spec)
	}
	return run.Fields("commands", ownChecks(l), "base", nil, "upstream", nil, "files", files, "scratch", true,
		"artifacts", []any{}, "lines", config.NoLimit.Said(), "limit", seconds(l.ceiling), "silence", seconds(l.silence))
}
