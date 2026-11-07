package tick

import (
	"slices"
	"time"

	"agentkit/internal/notify"
	"agentkit/internal/run"
	"agentkit/internal/seat"
)

// keptStalls is whether each of watch.json's stalls is one the health row carries: a plain one
// (seat.PlainStalls), or one it keeps of a login its harness's verb refused, whose owner was told
// (keepLogin).  One a parked run raised, or untold, is Python's to retract or tell again.
func keptStalls(stalls *run.Object) bool {
	return !slices.ContainsFunc(stalls.Keys(), func(name string) bool {
		entry, _ := stalls.Get(name).(*run.Object)
		return !loginTold(entry) && !seat.PlainStalls(run.Fields(name, stalls.Get(name)))
	})
}

// loginTold is whether a stall is one keepLogin keeps, its owner told.
func loginTold(entry *run.Object) bool {
	if entry == nil {
		return false
	}
	_, said := entry.Get("notice").(string)
	return entry.Get("kind") == "auth" && entry.Get("evidence") == "verb" && entry.Str("harness") != "" && said && entry.Truthy("told")
}

// askLogins is the health row's first ask (watch.health): every harness an earlier pass recorded a
// no for asked again (recordAuth), whether or not a seat of its can be read this pass, so a login
// that came back clears itself off every seat; those asked.  A real tick keeps each answer that
// changed in watch.json too, under its lock, before any seat's word reads it there; errLeft,
// nothing written, where watch.json holds what Go cannot write back.
func (t *ticking) askLogins() (map[string]bool, error) {
	asked, held := map[string]bool{}, t.state.Dict("auth_out")
	if held == nil {
		return asked, nil
	}
	var changed []string
	harnesses := held.Keys()
	slices.Sort(harnesses)
	for _, harness := range harnesses {
		if t.loggedOut(harness) == nil {
			continue
		}
		before := held.Get(harness)
		asked[harness] = true
		t.recordAuth(harness)
		if !run.Equal(before, held.Get(harness)) {
			changed = append(changed, harness)
		}
	}
	if t.dry || len(changed) == 0 {
		return asked, nil
	}
	kept := false
	err := locked(func() error {
		current, ok := loadState()
		if !ok || current.Has("auth_out") && current.Dict("auth_out") == nil {
			return nil
		}
		if current.Dict("auth_out") == nil {
			current.Set("auth_out", run.NewObject())
		}
		for _, harness := range changed {
			current.Dict("auth_out").Set(harness, held.Get(harness))
		}
		kept = true
		return writeState(current)
	})
	if err == nil && !kept {
		err = errLeft
	}
	return asked, err
}

// recordAuth is watch.record_auth: the harness's seat login asked and its answer kept in the
// tick's `auth_out`, dated from when that answer began; one it could not give keeps the last.
func (t *ticking) recordAuth(harness string) {
	if t.state.Dict("auth_out") == nil {
		t.state.Set("auth_out", run.NewObject())
	}
	answered, yes, why := authOK(harness, "seat")
	if !answered {
		return
	}
	record := t.state.Dict("auth_out")
	at := any(run.Float(epoch(time.Now())))
	if previous := record.Dict(harness); previous != nil && previous.Get("ok") == yes {
		at = previous.Get("at")
	}
	record.Set(harness, run.Fields("ok", yes, "why", why, "at", at))
}

// loggedOut is watch.logged_out of the tick's `auth_out`: the harness's answer where it is a no.
func (t *ticking) loggedOut(harness string) *run.Object {
	if held := t.state.Dict("auth_out"); held != nil && held.Dict(harness) != nil && held.Dict(harness).Get("ok") == false {
		return held.Dict(harness)
	}
	return nil
}

// loggedIn is watch.logged_in of the tick's `auth_out`: whether the harness's answer is a yes.
func (t *ticking) loggedIn(harness string) bool {
	held := t.state.Dict("auth_out")
	return held != nil && held.Dict(harness) != nil && held.Dict(harness).Get("ok") == true
}

// loginHeld is the health row's reading of a seat holding a stall kept of a refused login
// (watch.health), its own asked again where its screen shows its harness's logout words: the stall
// stands while that login is out on record, or while the one it was kept for has not passed again,
// a non-answer being no yes; it is back once that passes, the seat's own not out, where the row
// clears it (clearLogin) and looks again, as it would at a seat on its own word.  Neither where
// Python's tick does more: asks the seat's own login, not refused at the pass's first ask, begins
// another harness's stall, types past logout words, clears or waits on a refusal its file keeps,
// or answers its notice by its output.
func (t *ticking) loginHeld(live seat.Live, held *run.Object, stale map[string]bool) (stands, back bool) {
	if live.Login != nil {
		t.recordAuth(live.Own)
	}
	if t.loggedOut(live.Own) != nil {
		return held.Str("harness") == live.Own, false
	}
	if live.Login != nil || !stale[live.Own] {
		return false, false
	}
	if !t.loggedIn(held.Str("harness")) {
		return true, false
	}
	return false, !live.File.Truthy("usage_refusal") && quietLogin(live) && ownerWaits(live)
}

// clearLogin is watch.forget(acknowledge=False, notice=...) of a seat whose refused login passes
// again: under watch.json's lock its alert generation moved on and its stall gone, and its notice
// seen where it is still that login's (notify.Retract), the tick's own state then synced with
// what was written, as watch.health does before it says so.  A dry tick only drops the stall from
// what it reads.  False, nothing written, where watch.json holds a newer generation of the seat,
// or what Go cannot write back.
func (t *ticking) clearLogin(live seat.Live, held *run.Object) (bool, error) {
	line := live.Name + ": " + held.Str("harness") + " can authenticate again; cleared needs login"
	if t.dry {
		t.state.Dict("stalls").Delete(live.Name)
		t.log.line(line)
		return true, nil
	}
	carried := false
	err := locked(func() error {
		current, ok := loadState()
		if !ok {
			return nil
		}
		seen, _ := run.Num(current.Dict("seen_at").Get(live.Name))
		before, _ := run.Num(t.state.Dict("seen_at").Get(live.Name))
		if seen > before {
			return nil
		}
		seat.NextGeneration(current, live.Name, time.Now())
		if err := notify.Retract(live.Name, held.Str("notice")); err != nil {
			return err
		}
		if err := writeState(current); err != nil {
			return err
		}
		carried = true
		syncSeen(t.state, current)
		return nil
	})
	if carried {
		t.log.line(line)
	}
	return carried, err
}
