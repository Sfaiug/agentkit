package tick

import (
	"cmp"
	"errors"
	"fmt"
	"path/filepath"

	"agentkit/internal/config"
	"agentkit/internal/launch"
	"agentkit/internal/loop"
	"agentkit/internal/run"
)

// loginResume is watch.resume_waiting_login: a run parked on an expired login goes on by Go's own
// resume, in the same worktree, round and conversation, once its harness's `auth` verb says yes,
// asked once a tick for each harness.  Only a yes is a login back: an adapter that did not answer
// lifts nothing.  One whose worktree went meanwhile is an interruption, waiting on no login.
func (t *ticking) loginResume() error {
	back := map[string]bool{}
	var left error
	if !run.Every(func(dir string, record *run.Object) bool {
		if record.Str("state") != "waiting_login" {
			return true
		}
		harness := record.Str("waiting_for")
		if _, asked := back[harness]; !asked && harness != "" {
			_, back[harness], _ = authOK(harness)
		}
		left = t.loginRun(dir, record, harness, back[harness])
		return left == nil
	}) {
		return cmp.Or(left, errLeft)
	}
	return nil
}

// loginRun is the row's move on one run parked on that harness's login: errLeft where it is Python's.
func (t *ticking) loginRun(dir string, record *run.Object, harness string, back bool) error {
	id, at := filepath.Base(dir), epoch(t.clock())
	if !back {
		// What an earlier pass left of a login back, and of pacing its launch, belongs to an
		// episode that is over: the run would go on reading as about to resume, and the next
		// recovery would sit out a window timed against the last one.
		if !record.Truthy("login_back_at") && !record.Truthy("login_resume_at") {
			return nil
		}
		if t.dry {
			return errLeft // Python's dry tick takes them off too; Go's writes nothing
		}
		return t.changeLogin(id, dir, record, func(current *run.Object) {
			current.Delete("login_resume_at")
			current.Delete("login_back_at")
		}, func() {
			if record.Get("login_back_at") != nil {
				t.log.line(fmt.Sprintf("%s: the %s login went out again", id, harness))
			}
		})
	}
	// the login back goes on the record before the pacing can skip the pass: a run waiting out
	// its launch's window never goes on reporting a login that is no longer expired
	backAt := func(current *run.Object) {
		if !current.Truthy("login_back_at") {
			current.Set("login_back_at", at)
		}
	}
	if last, ok := dated(record, "login_resume_at"); ok && 0 <= at-last && at-last < resumeEvery {
		if t.dry || record.Truthy("login_back_at") {
			return nil
		}
		return t.changeLogin(id, dir, record, backAt, nil)
	}
	if !directory(record.Str("worktree")) {
		worktree := cmp.Or(record.Str("worktree"), "(none)")
		if t.dry {
			t.log.line(fmt.Sprintf("would interrupt %s: the %s login is back but its worktree %s is gone", id, harness, worktree))
			return nil
		}
		// the login is back and the work is not: an interruption names its own reason, where
		// a run still waiting for a login would send the owner to sign in for nothing
		reason := fmt.Sprintf("The %s login is back, but this run's worktree %s is gone; it cannot be resumed where it stopped.", harness, worktree)
		return t.changeLogin(id, dir, record, func(current *run.Object) {
			for _, key := range loop.LoginKeys {
				current.Delete(key)
			}
			run.SetAll(current, "state", "interrupted", "interrupted_at", at, "interruption_reason", reason, "recovery_pending", true)
		}, func() { t.log.line("WARN " + id + ": " + reason) })
	}
	if t.dry {
		t.log.line(fmt.Sprintf("would resume %s: %s can authenticate again", id, harness))
		return nil
	}
	code, why, err := launch.ResumeExpected(id, record, nil, nil)
	switch {
	case errors.Is(err, launch.ErrPython):
		return errLeft
	case err == nil && code == 0:
		t.log.line(fmt.Sprintf("resumed %s: the %s login is back", id, harness))
		return nil
	}
	t.log.line(fmt.Sprintf("WARN could not resume %s: %s", id, cmp.Or(why, fmt.Sprint(err))))
	// a launch that never started waits resumeEvery as one still on its way
	return t.changeLogin(id, dir, record, func(current *run.Object) {
		backAt(current)
		current.Set("login_resume_at", at)
	}, nil)
}

// changeLogin writes the row's move on the run as the row read it, then says so where said is
// given: one that moved since is the next tick's to read again, and one that cannot be written
// keeps no other run from its move.
func (t *ticking) changeLogin(id, dir string, read *run.Object, move func(*run.Object), said func()) error {
	err := run.Change(dir, func(current *run.Object) error {
		if !run.Equal(current, read) {
			return errMovedRun
		}
		move(current)
		return nil
	})
	switch {
	case err == nil && said != nil:
		said()
	case err != nil && !errors.Is(err, errMovedRun):
		t.log.line(fmt.Sprintf("WARN cannot check run %s: %s", id, config.PyError(err)))
	}
	return nil
}
