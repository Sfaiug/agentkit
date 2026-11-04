package launch

import (
	"io"

	"agentkit/internal/run"
)

// Resume is `ak run resume <id>`, Python's resume_run on a dead run Go can pick up from: its
// refusals in its words, `ak run`'s exit status, and why it refused. Anything else it leaves to
// Python (ErrPython) before it writes anything.
func Resume(id string, bg bool, out, errOut io.Writer) (int, string, error) {
	return resume(id, bg, nil, out, errOut)
}

// ResumeExpected adopts only the wait the tick decided to resume, as spawn_bg(expected)
// does: a later attempt or a stop cannot be resumed on that decision.
func ResumeExpected(id string, expected *run.Object) (int, string, error) {
	return resume(id, true, expected, io.Discard, io.Discard)
}
