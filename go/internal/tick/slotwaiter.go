package tick

import (
	"errors"
	"path/filepath"

	"agentkit/internal/launch"
	"agentkit/internal/run"
)

// restartWaiter is recover_runs' slot waiter: a run waiting for a slot is held by its own waiting
// process, and nothing would ever start one whose process died, so Go's own resume starts it again,
// still waiting and its place in line kept, adopting only the record as read (spawn_bg's expected).
// The dead-loops pass gets to most first; this one finds those it left, inside their launch's grace
// or waiting out a death's backoff, whose resume is Python's.
func (t *ticking) restartWaiter(dir string, record *run.Object) error {
	id := filepath.Base(dir)
	if t.dry {
		t.log.line("would restart the slot waiter for " + id)
		return nil
	}
	code, why, err := launch.ResumeExpected(id, record, nil, nil)
	switch {
	case errors.Is(err, launch.ErrPython):
		return errLeft
	case err != nil:
		return err
	case code != 0:
		return errors.New(why) // spawn_bg's refusal, which Python's pass warns of as it does a read it could not make
	}
	t.log.line("restarted the slot waiter for " + id)
	return nil
}
