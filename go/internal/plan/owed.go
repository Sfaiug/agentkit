package plan

import (
	"os"
	"time"

	"agentkit/internal/config"
)

// Owes is whether the seat's plan owes work: an open line, or a plan nothing can read, which
// proves nothing done (stop.owed).  A deferred line counts whether or not a run has it: the runs
// are not Go's to read here yet.
func Owes(name string) bool {
	current, _, err := config.ResolveSession(name)
	if err != nil {
		return true
	}
	lines, err := read(current)
	if err != nil {
		return true
	}
	for _, line := range lines {
		if open(line) {
			return true
		}
	}
	return false
}

// DoneAt is when the seat's finished plan (Finished) was last written, which ticked its last
// line, as stop.question_refused dates it: zero where it is not finished or nothing can date it,
// ErrUnread where Finished is.
func DoneAt(name string) (time.Time, error) {
	finished, err := Finished(name)
	if !finished {
		return time.Time{}, err
	}
	file, err := path(name)
	if err != nil {
		return time.Time{}, nil
	}
	info, err := os.Stat(file)
	if err != nil {
		return time.Time{}, nil
	}
	return info.ModTime(), nil
}
