package usage

import (
	"math"

	"agentkit/internal/run"
)

// dryFor is how long a refusal that named no time, beside meters naming none either, parks its
// provider: long enough that nothing hands the same work straight back to it.
const dryFor = 3600.0

// MarkExhausted parks a provider, or that account of it ("" for the provider), that has just
// refused a worker until it says it can work again, the deadline it recorded, Python's
// usage.mark_exhausted: until is the harness's own "try again at", 0 where its refusal named none,
// else the soonest of its own windows still to roll over, dryFor at most where no meter shows the
// refusal, as a window with room did not refuse.  The mark sits in the snapshot beside the meters,
// so every later pick in every run reads it; an account's is its own.
func MarkExhausted(provider, account string, until float64) float64 {
	now := clock()
	prov := run.NewObject()
	if readings, err := Collected(); err == nil {
		prov = object(readings.providers.Get(provider))
	}
	if account != "" {
		prov = object(object(prov.Get("accounts")).Get(account))
	}
	said := until > now
	if !said {
		until = nextWindow(prov, now)
	}
	ends := run.NewObject()
	shown, by := 0.0, ""
	for _, meter := range objects(prov.Get("meters")) {
		name, named := meter.Get("name").(string)
		end, ended := number(meter.Get("resets_at"))
		if !named || !ended {
			continue
		}
		ends.Set(name, run.Float(end))
		used, _ := number(meter.Get("used"))
		window, sized := number(meter.Get("window_secs"))
		// never a session, or a window that does not say it is none, when the refusal outlasts one
		if used >= 100 && !((!sized || window == sessionSecs) && until-now > sessionSecs) && (end > shown || end == shown && name > by) {
			shown, by = end, name
		}
	}
	if !said && by == "" {
		until = math.Min(until, now+dryFor)
	}
	change := func(providers *run.Object, _ float64) *run.Object {
		old := object(providers.Get(provider))
		accounts, record := object(old.Get("accounts")), old
		if account != "" {
			record = object(accounts.Get(account))
		}
		if len(record.Keys()) == 0 {
			record = prov.Copy()
		}
		// a credit spent since refused the week it replaced, which that credit has lifted
		if spent, _ := number(record.Get("reset_spent_at")); spent < now {
			run.SetAll(record, "exhausted_until", run.Float(until), "exhausted_at", run.Float(now), "exhausted_ends", ends, "exhausted_by", shownBy(by))
			if account == "" {
				providers.Set(provider, record)
			} else {
				accounts.Set(account, record)
				old.Set("accounts", accounts)
				providers.Set(provider, old)
			}
		}
		return record
	}
	if _, err := write(change, nil); err != nil {
		return until // a snapshot that cannot be written costs a re-probe
	}
	return until
}

// shownBy is the meter that showed the refusal as a record holds it, null for none.
func shownBy(name string) any {
	if name == "" {
		return nil
	}
	return name
}

// nextWindow is the soonest of the provider's windows still to roll over, now+dryFor where none
// does, Python's _next_window or DRY_FOR.
func nextWindow(prov *run.Object, now float64) float64 {
	found := math.Inf(1)
	for _, meter := range objects(prov.Get("meters")) {
		if end, ok := number(meter.Get("resets_at")); ok && end > now {
			found = math.Min(found, end)
		}
	}
	if math.IsInf(found, 1) {
		return now + dryFor
	}
	return found
}
