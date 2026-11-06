package launch

import (
	"io"

	"agentkit/internal/run"
)

// Resume is `ak run resume <id>`, Python's resume_run on a dead run Go can pick up from: its
// refusals in its words, `ak run`'s exit status, and why it refused. Anything else it leaves to
// Python (ErrPython) before it writes anything.
func Resume(id string, bg bool, out, errOut io.Writer) (int, string, error) {
	return resume(id, bg, nil, nil, nil, out, errOut)
}

// ResumeExpected adopts only the wait the tick decided to resume, as spawn_bg(expected)
// does: a later attempt or a stop cannot be resumed on that decision.  order, where the tick
// gives one, is what it writes on the record ordering the resume (watch._arm_resume): written
// with the resume taking the record up, so a resume left to Python leaves nothing written.
// noted, where the tick gives one, writes its line in the run's log once the order has landed and
// before the driver starts, as Python's tick notes it before its launch: the driver's lines follow.
func ResumeExpected(id string, expected *run.Object, order func(*run.Object), noted func()) (int, string, error) {
	return resume(id, true, expected, order, noted, io.Discard, io.Discard)
}
