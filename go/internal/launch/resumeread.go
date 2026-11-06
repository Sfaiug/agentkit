package launch

import (
	"io"
	"path/filepath"

	"agentkit/internal/run"
)

// Resume is `ak run resume <id> [--rounds N]`, Python's resume_run on a dead run Go can pick up
// from, rounds, where not 0, raising the budget of a FAIL at it: its refusals in its words, `ak
// run`'s exit status, and why it refused. Anything else it leaves to Python (ErrPython) before it
// writes anything.
func Resume(id string, rounds int, bg bool, out, errOut io.Writer) (int, string, error) {
	if rounds == 0 {
		return resume(id, bg, nil, nil, nil, out, errOut)
	}
	dir := filepath.Join(run.Runs(), id)
	record, _ := run.Read(dir)
	if !reached(dir, record) {
		return 0, "", ErrPython
	}
	order, why, err := raise(dir, record, rounds)
	if err != nil || why != "" {
		return 2, why, err
	}
	return resume(id, bg, record, order, nil, out, errOut)
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
