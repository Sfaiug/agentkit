package loop

import (
	"fmt"
	"os"
	"path/filepath"

	"agentkit/internal/run"
)

// sayResume says the run resumes where this driver takes up a resume's receipt as its own, before
// it waits in line for its slot, as Python's resume_run logs it before its drive: the receipt names
// what it resumes from until its slot comes (settle).  Read under the run's lock, which its resume
// holds until the receipt names this process (Start).
func (l *loop) sayResume() {
	run.Change(l.dir, func(record *run.Object) error {
		pid, _ := record.Int("pid")
		l.resumed = record.Truthy("resume_from") && pid == os.Getpid()
		return nil
	})
	if l.resumed {
		l.say(fmt.Sprintf("resume %s: %s", l.id, filepath.Join(l.dir, "task.md")))
	}
}
