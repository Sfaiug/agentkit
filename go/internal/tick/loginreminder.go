package tick

import (
	"agentkit/internal/config"
	"agentkit/internal/harness"
	"agentkit/internal/logins"
	"agentkit/internal/notify"
)

const remindWithin = 3 * 86400 // how near its end a login pages the owner, once a local day (logins.REMIND_WITHIN)

// remindLogins is the login reminder row (logins.remind): every subscription's login refreshed,
// then the owner paged once a local day for each that ends within remindWithin or has ended, the
// card naming only the subscription, `Claude II login`, the outbox the whole sentence.  A new
// login moves its end past the window, or to none, and the pages stop.
func (t *ticking) remindLogins() error {
	now := t.clock()
	kept, err := notify.RefreshLogins(epoch(now))
	if err != nil {
		return err
	}
	for _, provider := range kept.Keys() {
		listed, err := config.Accounts(provider)
		if err != nil {
			return err
		}
		company, _ := harness.Company(provider)
		for _, account := range kept.Dict(provider).Keys() {
			login := kept.Dict(provider).Dict(account)
			if ends, known := login.Num("ends"); !known || ends-epoch(now) > remindWithin {
				continue
			}
			label := config.AccountLabel(listed, account, company)
			key := "login:" + provider + ":" + account + ":" + now.Format("2006-01-02")
			if err := notify.Remind(key, label+" login", label+" "+logins.Ending(login, now)+". Log in again from ak.", t.log.line, t.log.errOut); err != nil {
				return err
			}
		}
	}
	return nil
}
