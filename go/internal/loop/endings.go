package loop

import (
	"errors"

	"agentkit/internal/gitcall"
	"agentkit/internal/run"
	"agentkit/internal/worker"
)

// An exhausted is work a later run can pick up: a provider spent, with window the one it waits on,
// or nobody left to take the role.  Never an error, a remedy nothing can act on.
type exhausted struct {
	why    string
	window bool
}

func (e *exhausted) Error() string { return e.why }

// A killedTwice is a worker turn killed by signal twice within a minute: a person must look.
type killedTwice struct{ why string }

func (k *killedTwice) Error() string { return k.why }

// parked is the record of a run that stopped with nothing executed and nothing judged, and what the
// log says of it, as Python's drive: the login a run waits for, resumed the moment its `auth` verb
// passes; a kill, resumable by a person; a window or a stopped tool.  false for any other ending.
func parked(err error) (string, func(*run.Object), bool) {
	var login *worker.LoginExpired
	var killed *killedTwice
	var tired *exhausted
	var stopped *gitcall.Stopped
	switch {
	case errors.As(err, &login):
		return "waiting for login: " + login.Error(), func(record *run.Object) {
			record.Set("waiting_for", login.Harness)
			markState(record, "waiting_login", login.Error())
		}, true
	case errors.As(err, &killed):
		return "killed: " + killed.why, func(record *run.Object) {
			run.SetAll(record, "state", "interrupted", "interrupted_at", clock(), "interruption_reason", killed.why, "recovery_pending", true)
		}, true
	case errors.As(err, &tired):
		return "exhausted: " + tired.why, func(record *run.Object) { parkExhausted(record, tired.why, tired.window) }, true
	case errors.As(err, &stopped):
		return "exhausted: " + stopped.Why, func(record *run.Object) { parkExhausted(record, stopped.Why, false) }, true
	}
	return "", nil, false
}

// parkExhausted is Python's mark_state and park_exhausted: only a spent provider waits on a window.
func parkExhausted(record *run.Object, why string, window bool) {
	markState(record, "exhausted", why)
	if window {
		record.Set("quota_dry", true)
		return
	}
	record.Delete("quota_dry")
	record.Delete("refusal_retry")
}

// markState is how a run stopped, Python's mark_state: what an earlier wait paced means nothing now.
func markState(record *run.Object, state, why string) {
	run.SetAll(record, "state", state, "finished_at", clock(), "error", why)
	DropErrorRetry(record) // an error's retry belongs to the error: any other mark ends that episode
	if state != "waiting_login" {
		for _, key := range []string{"waiting_for", "login_resume_at", "login_back_at"} {
			record.Delete(key)
		}
	}
}
