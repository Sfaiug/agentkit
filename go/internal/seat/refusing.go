package seat

import (
	"errors"
	"path/filepath"
	"slices"

	"agentkit/internal/config"
	"agentkit/internal/run"
)

// runOnALogin: [1a] a run of its own parked on a login, or one a login keeps refusing, is news of a
// login the owner has to go and fix, on a seat nobody is in too: the oldest such run names the
// login and dates the word (owedOf).  The run is the whole of the evidence: nothing here asks its
// login's verb, which the tick's login resume does.
func runOnALogin(facts climbing) (*answer, error) {
	if _, err := aRunOfItsOwn(facts); err != nil {
		return nil, err
	}
	login, err := owedOf(facts.mine)
	if login == nil {
		return nil, err
	}
	return loginExpired(login.Login, login.Since)
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
