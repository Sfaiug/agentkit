package usage

import (
	"agentkit/internal/config"
	"agentkit/internal/logins"
)

// Price is what sub's login account ("" its usual one) costs a month, Python's usage.price: the
// `price` on its table, in whatever its owner pays in, else the list price of the plan
// state/logins.json says the login is on now on the `[plans]` of the harness that asks it; nil
// for neither.
func Price(sub config.Subscription, account string) (*float64, error) {
	if sub.Price != nil {
		return sub.Price, nil
	}
	kept := logins.Of(sub.Name, account)
	if kept == nil {
		return nil, nil
	}
	return config.PlanPrice(logins.Harness(sub), kept.Str("plan"))
}

// price is that login's Price.  Its one failure, a manifest that does not load, listed has
// handed over already for every reading that has sources.
func (r *Readings) price(each login) *float64 {
	price, _ := Price(r.source(each.provider).Subscription, each.account)
	return price
}
