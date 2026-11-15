package seat

import "agentkit/internal/run"

// Owed is a login a run of the seat's own waits on its owner for (watch.owed_login), as the oldest
// such run by its ending gives it, the first of its runs winning a tie: that login, when the run
// parked, and what it said ("" for nothing).
type Owed struct {
	Login      string
	Since, Why any
}

// owedLogin is the login the run in that directory waits on its owner for: one it parked on that
// the tick has not found back yet (`login_back_at`), else one that keeps refusing it (Refusing);
// "" for none.  False where Python reads what Go does not: a login named by no text.
func owedLogin(dir string, record *run.Object) (string, bool) {
	if record.Str("state") == "waiting_login" && !record.Truthy("login_back_at") {
		login, named := record.Get("waiting_for").(string)
		return login, named || !record.Truthy("waiting_for")
	}
	return Refusing(dir, record)
}

// owedOf is the seat's Owed among its runs, nil for none; ErrUnread where Go cannot read one's.
func owedOf(mine []ran) (*Owed, error) {
	var oldest *Owed
	first := 0.0
	for _, each := range mine {
		login, known := owedLogin(each.name, each.record)
		if !known {
			return nil, ErrUnread
		}
		if at := run.FirstNumber(each.record, "finished_at"); login != "" && (oldest == nil || at < first) {
			why := each.record.Get("error")
			if !each.record.Truthy("error") {
				why = ""
			}
			oldest, first = &Owed{Login: login, Since: each.record.Get("finished_at"), Why: why}, at
		}
	}
	return oldest, nil
}
