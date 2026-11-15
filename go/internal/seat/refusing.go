package seat

import (
	"errors"
	"path/filepath"
	"slices"

	"agentkit/internal/config"
	"agentkit/internal/run"
)

// runOnALogin: [1a] a run of its own that a login keeps refusing is news of a login the owner has
// to go and fix, on a seat nobody is in too.  The oldest such run by its ending names the login and
// dates the word, the first of its runs winning a tie (min).  A run parked on a login, the rung's
// other half, has no view yet, which hands the home over (viewRun).
func runOnALogin(facts climbing) (*answer, error) {
	if _, err := aRunOfItsOwn(facts); err != nil {
		return nil, err
	}
	var oldest *ran
	login := ""
	for i, each := range facts.mine {
		owed, known := Refusing(each.name, each.record)
		if !known {
			return nil, ErrUnread
		}
		if owed != "" && (oldest == nil || run.FirstNumber(each.record, "finished_at") < run.FirstNumber(oldest.record, "finished_at")) {
			oldest, login = &facts.mine[i], owed
		}
	}
	if oldest == nil {
		return nil, nil
	}
	return loginExpired(login, oldest.record.Get("finished_at"))
}

// Refusing is the login that keeps refusing the run in that directory while it has not ended
// (watch.refusing_login): the first in login-refusals.json to hold two refusals or more since it
// last answered, the run's name among them (login_refusals.owed); "" for none.  A file missing,
// unreadable or no object keeps nothing (login_refusals._kept).  False where Python reads what Go
// does not: a login whose refusals are no list, or text Go cannot keep.
func Refusing(dir string, record *run.Object) (string, bool) {
	if !run.GoingState(record) {
		return "", true
	}
	kept, err := run.ReadJSON(filepath.Join(config.Home(), "state", "login-refusals.json"))
	if err != nil || kept == nil {
		return "", !errors.Is(err, run.ErrLoneSurrogate)
	}
	for _, login := range kept.Keys() {
		refusals, listed := kept.Get(login).([]any)
		if !listed {
			return "", false
		}
		if len(refusals) >= 2 && slices.Contains(refusals, any(filepath.Base(dir))) {
			return login, true
		}
	}
	return "", true
}
