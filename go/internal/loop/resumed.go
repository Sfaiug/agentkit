package loop

import (
	"fmt"
	"os"
	"path/filepath"

	"agentkit/internal/run"
)

// takeResume takes up a resume's receipt as this driver's own, as Python's resume_run does in the
// process its spawn starts: the run says it resumes before it waits in line for its slot.  The
// receipt names what it resumes from until its slot comes (settle), and is read under the run's
// lock, which its resume holds until the receipt names this process (Start).
func (l *loop) takeResume() {
	run.Change(l.dir, func(record *run.Object) error {
		pid, _ := record.Int("pid")
		l.resumed = record.Truthy("resume_from") && pid == os.Getpid()
		return nil
	})
	if l.resumed {
		l.say(fmt.Sprintf("resume %s: %s", l.id, filepath.Join(l.dir, "task.md")))
	}
}
