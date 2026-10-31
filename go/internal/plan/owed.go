package plan

import (
	"os"
	"time"

	"agentkit/internal/config"
)

// Owes is whether the seat's plan owes work: an open line, or a plan nothing can read, which
// proves nothing done (stop.owed).  A deferred line counts whether or not a run has it: the runs
// are not Go's to read here yet.  Where it owes none and holds done work, done is when it was
// last written (plan.finished, dated as stop.question_refused dates it), zero otherwise.
func Owes(name string) (owed bool, done time.Time) {
	current, _, err := config.ResolveSession(name)
	if err != nil {
		return true, done
	}
	lines, err := read(current)
	if err != nil {
		return true, done
	}
	finished := false
	for _, line := range lines {
		if open(line) {
			return true, done
		}
		finished = finished || boxed(line)
	}
	file, err := path(current)
	if !finished || err != nil {
		return false, done
	}
	if info, err := os.Stat(file); err == nil {
		done = info.ModTime()
	}
	return false, done
}
