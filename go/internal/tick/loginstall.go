package tick

import (
	"cmp"
	"fmt"
	"slices"
	"strings"
	"time"

	"agentkit/internal/config"
	"agentkit/internal/notify"
	"agentkit/internal/run"
	"agentkit/internal/seat"
)

// loginOut is the health row's reading of a seat's own login (watch.health): the answer
// `auth_out` keeps for its harness where that login is out (watch.logged_out), and whether that
// decides the seat.  Its `auth seat` verb is asked where the seat shows its harness's logout words
// (watch.record_auth); out is its no, or where it answers nothing, a no an earlier seat's look kept
// this tick, whose `at` stands while the answer is the same.  A yes, which Python's tick types
// past, and a login out where the row would do more than keep its stall and say it (keepLogin),
// leave the seat to Python, nothing kept: a dry tick, no screen to read, a notice standing, or the
// seat not then waiting on its owner.  Undecided, quietLogin reads the seat.
func (t *ticking) loginOut(live seat.Live) (*run.Object, bool) {
	held := t.state.Dict("auth_out")
	if held != nil {
		held = held.Dict(live.Own)
	}
	if held != nil && held.Get("ok") != false {
		held = nil
	}
	if t.dry || strings.TrimFunc(live.Pane, config.Space) == "" || notify.Last(live.Name) != nil || !ownerWaits(live) {
		return nil, held != nil
	}
	if live.Login == nil {
		return held, held != nil
	}
	answered, yes, why := authOK(live.Own, "seat")
	switch {
	case !answered:
		return held, held != nil
	case yes:
		return nil, true
	case held != nil:
		return run.Fields("ok", false, "why", why, "at", held.Get("at")), true
	}
	return run.Fields("ok", false, "why", why, "at", run.Float(epoch(time.Now()))), true
}

// keepLogin is watch.health on a seat whose own login is out, under watch.json's lock: the
// answer kept in `auth_out`, the seat's stall one of kind `auth` begun when that answer was, whose
// notice says the harness's remedy out of its manifest's `[auth]`, the owner paged with it once
// (notify.Alert) and the stall told, all written there, before the seat's word reads them.  The
// tick keeps them too, for its save.  Where watch.json holds a newer generation of the seat, or
// what Go or Python's record_auth cannot read, nothing is written and the seat is Python's.
func (t *ticking) keepLogin(live seat.Live, answer *run.Object) (bool, error) {
	auth, err := config.Section(live.Own, "auth")
	if err != nil {
		return false, nil
	}
	title, _ := auth["title"].(string)
	remedy, _ := auth["remedy"].(string)
	title = cmp.Or(title, live.Own)
	text := fmt.Sprintf("%s (%s) needs login: open the host, press this session's number, and %s.", live.Name, title, cmp.Or(remedy, "log in again"))
	since := answer.Get("at")
	signature := live.Login
	if signature == nil { // its screen says no logout words: what the verb said is the evidence
		signature = answer.Get("why")
	}
	entry := run.Fields("kind", "auth", "harness", live.Own, "since", since, "evidence", "verb", "signature", signature, "pane", live.Pane, "notice", text)
	line, carried := live.Name+": "+title+" needs login; asked the user", false
	err = locked(func() error {
		current, ok := loadState()
		if !ok {
			return nil
		}
		seen, _ := run.Num(current.Dict("seen_at").Get(live.Name))
		before, _ := run.Num(t.state.Dict("seen_at").Get(live.Name))
		states := []*run.Object{current, t.state}
		if seen > before || slices.ContainsFunc(states, func(state *run.Object) bool { return state.Has("auth_out") && state.Dict("auth_out") == nil }) {
			return nil
		}
		carried = true
		if err := notify.Alert(live.Name, text, "auth:"+live.Name+":"+live.Own+":"+run.Text(since), t.log.errOut); err != nil {
			line = "WARN " + live.Name + ": notification was not accepted; retry required"
		} else {
			entry.Set("told", run.Float(epoch(time.Now())))
		}
		for _, state := range states {
			if state.Dict("auth_out") == nil {
				state.Set("auth_out", run.NewObject())
			}
			state.Dict("auth_out").Set(live.Own, answer)
			state.Dict("stalls").Set(live.Name, entry)
		}
		return writeState(current)
	})
	if carried {
		t.log.line(line)
	}
	return carried, err
}
