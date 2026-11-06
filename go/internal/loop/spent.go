package loop

import (
	"agentkit/internal/history"
	"agentkit/internal/run"
)

// spent counts in the run's history row what the attempt in out, on the harness name, spent,
// however it ended, Python's history_role_tokens: a refused, parked or killed turn spent too.
func (l *loop) spent(name, out string) {
	if record, _ := run.Read(l.dir); record != nil {
		history.Spent(record, name, out, l.say)
	}
}
