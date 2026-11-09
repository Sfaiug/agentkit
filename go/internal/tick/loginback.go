package tick

import (
	"slices"
	"time"

	"agentkit/internal/config"
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

// unlooked is whether a seat tmux holds with its panes all exited, which Health publishes without
// its look, has a login for the health row to ask after, as Python's look at such a seat still does
// (watch.health): a stall of one held, or its own refused on record.  A home with neither is not
// read again for it.
func (t *ticking) unlooked(stalls *run.Object) bool {
	asks := func(name string) bool {
		held, _ := stalls.Get(name).(*run.Object)
		return held != nil && held.Get("kind") == "auth" || t.loggedOut(config.SeatHarness(name)) != nil
	}
	answers := t.state.Dict("auth_out")
	if !slices.ContainsFunc(stalls.Keys(), asks) && (answers == nil || !slices.ContainsFunc(answers.Keys(), func(harness string) bool { return t.loggedOut(harness) != nil })) {
		return false
	}
	exited, known := seat.Exited(time.Now())
	return !known || slices.ContainsFunc(exited, asks)
}

// askLogins is the health row's first ask (watch.health): every harness an earlier pass recorded a
// no for asked again (recordAuth), whether or not a seat of its can be read this pass, so a login
// that came back clears itself off every seat, each answer that changed kept in watch.json too
// (keepAnswers) before any seat's word reads it there; errLeft, nothing written, where watch.json
// holds what Go cannot write back.
func (t *ticking) askLogins() error {
	held := t.state.Dict("auth_out")
	if held == nil {
		return nil
	}
	var changed []string
	harnesses := held.Keys()
	slices.Sort(harnesses)
	for _, harness := range harnesses {
		if t.loggedOut(harness) != nil && t.recordAuth(harness, false) {
			changed = append(changed, harness)
		}
	}
	if len(changed) == 0 {
		return nil
	}
	kept, err := t.keepAnswers(changed)
	if err == nil && !kept {
		err = errLeft
	}
	return err
}

// recordAuth is watch.record_auth: the harness's seat login asked, once a pass but again where
// fresh, and its answer kept in the tick's `auth_out`, dated from when that answer began; one it
// could not give keeps the last.  Whether what it keeps changed.
func (t *ticking) recordAuth(harness string, fresh bool) bool {
	if t.state.Dict("auth_out") == nil {
		t.state.Set("auth_out", run.NewObject())
	}
	if t.asked[harness] && !fresh {
		return false
	}
	if t.asked == nil {
		t.asked = map[string]bool{}
	}
	t.asked[harness] = true
	answered, yes, why := authOK(harness, "seat")
	if !answered {
		return false
	}
	record := t.state.Dict("auth_out")
	before, at := record.Get(harness), any(run.Float(epoch(time.Now())))
	if previous := record.Dict(harness); previous != nil && previous.Get("ok") == yes {
		at = previous.Get("at")
	}
	record.Set(harness, run.Fields("ok", yes, "why", why, "at", at))
	return !run.Equal(before, record.Get(harness))
}

// keepAnswers is the answer the tick keeps of each harness named written into watch.json, under its
// lock, for the seats' words to read there; a dry tick writes nothing.  False, nothing written,
// where watch.json holds what Go cannot write back.
func (t *ticking) keepAnswers(harnesses []string) (bool, error) {
	if t.dry {
		return true, nil
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
		for _, harness := range harnesses {
			current.Dict("auth_out").Set(harness, t.state.Dict("auth_out").Get(harness))
		}
		kept = true
		return writeState(current)
	})
	return kept, err
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
// (watch.health), its own login asked once this pass, and again where its screen shows its
// harness's logout words (recordAuth), whatever the record held of it: the stall stands while that
// login is out on record, or while the one it was kept for has not passed again, a non-answer being
// no yes; it is back once that passes, the seat's own not out, where the row clears it (clearLogin)
// and looks again, as it would at a seat on its own word.  Changed is whether the answer kept of the
// seat's own login changed, which its word reads.  Neither where Python's tick does more: begins
// another harness's stall, types past logout words, clears or waits on a refusal its file keeps, or
// answers its notice by its output.
func (t *ticking) loginHeld(live seat.Live, held *run.Object) (stands, back, changed bool) {
	changed = t.recordAuth(live.Own, live.Login != nil)
	switch {
	case t.loggedOut(live.Own) != nil:
		return held.Str("harness") == live.Own, false, changed
	case live.Login != nil:
		return false, false, changed
	case !t.loggedIn(held.Str("harness")):
		return true, false, changed
	}
	return false, !live.File.Truthy("usage_refusal") && quietLogin(live) && ownerWaits(live), changed
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

// dropped is the seat, and the notice its stall told, whose login stall a dry tick has just
// dropped (clearLogin), through its look again (lookAgain).  A real tick's retracted that notice;
// Python's dry tick, its watch.json still holding that stall told, answers nothing there by its
// output and types nothing past it.
var dropped struct{ name, notice string }

// standing is the seat's notice standing (notify.Last) as the health row's look reads it: none
// where it is the one a dry tick has just dropped the stall of (dropped).
func standing(name string) *run.Object {
	notice := notify.Last(name)
	if notice != nil && name == dropped.name && notice.Get("text") == dropped.notice {
		return nil
	}
	return notice
}

// lookAgain is the seat's look again (seat.Health) once the row kept its login, or cleared it
// (back), its word then reading what was written; after a dry tick's clear, the notice it would
// have retracted reads as gone (dropped).
func (t *ticking) lookAgain(name string, look func(seat.Live) bool, back *run.Object) (bool, error) {
	if back != nil && t.dry {
		dropped.name, dropped.notice = name, back.Str("notice")
		defer func() { dropped.name, dropped.notice = "", "" }()
	}
	return seat.Health(name, look, t.log.line, t.dry)
}
