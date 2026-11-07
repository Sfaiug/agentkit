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

// loginAsked is the health row's ask, of a seat showing its harness's logout words, of that
// harness's `auth seat` verb (watch.record_auth), made where a no leaves the row nothing to do there
// but keep that login's stall and say it (keepLogin): a real tick, a screen to read, no notice
// standing, and the seat then waiting on its owner.  Unasked or unanswered, quietLogin decides.
func (t *ticking) loginAsked(live seat.Live) (answered, yes bool, why string) {
	if t.dry || live.Login == nil || strings.TrimFunc(live.Pane, config.Space) == "" || notify.Last(live.Name) != nil || !ownerWaits(live) {
		return false, false, ""
	}
	return authOK(live.Own, "seat")
}

// keepLogin is watch.health on a seat whose own login its harness's verb refused, under
// watch.json's lock: the answer kept in `auth_out`, the seat's stall one of kind `auth` whose
// notice says the harness's remedy out of its manifest's `[auth]`, the owner paged with it once
// (notify.Alert) and the stall told, all written there, before the seat's word reads them.  The
// tick keeps them too, for its save.  Where watch.json holds a newer generation of the seat, or
// what Go or Python's record_auth cannot read, nothing is written and the seat is Python's.
func (t *ticking) keepLogin(live seat.Live, why string) (bool, error) {
	auth, err := config.Section(live.Own, "auth")
	if err != nil {
		return false, nil
	}
	title, _ := auth["title"].(string)
	remedy, _ := auth["remedy"].(string)
	title = cmp.Or(title, live.Own)
	text := fmt.Sprintf("%s (%s) needs login: open the host, press this session's number, and %s.", live.Name, title, cmp.Or(remedy, "log in again"))
	now := run.Float(epoch(time.Now()))
	entry := run.Fields("kind", "auth", "harness", live.Own, "since", now, "evidence", "verb", "signature", live.Login, "pane", live.Pane, "notice", text)
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
		if err := notify.Alert(live.Name, text, "auth:"+live.Name+":"+live.Own+":"+run.Text(now), t.log.errOut); err != nil {
			line = "WARN " + live.Name + ": notification was not accepted; retry required"
		} else {
			entry.Set("told", now)
		}
		for _, state := range states {
			if state.Dict("auth_out") == nil {
				state.Set("auth_out", run.NewObject())
			}
			state.Dict("auth_out").Set(live.Own, run.Fields("ok", false, "why", why, "at", now))
			state.Dict("stalls").Set(live.Name, entry)
		}
		return writeState(current)
	})
	if carried {
		t.log.line(line)
	}
	return carried, err
}
