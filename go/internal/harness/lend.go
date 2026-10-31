package harness

import "agentkit/internal/config"

// A Loan is a harness's login as its adapter's `lend` hands it to a turn on a rented machine:
// Copy, the login as JSON with nothing in it that renews it, since renewing a subscription login
// retires the one before it, and Ends, the epoch second it lapses.  With no Copy there is none to
// lend, and Line says so.
type Loan struct {
	Copy string
	Ends int64
	Line string
}

// Lend is that harness's login on login lent; false where Go does not lend that harness's login
// yet.
func Lend(name string, login config.Login) (Loan, bool) {
	if hook := plugins[name].lend; hook != nil {
		return hook(login), true
	}
	return Loan{}, false
}
