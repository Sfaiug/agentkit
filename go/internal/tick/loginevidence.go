package tick

import (
	"strings"

	"agentkit/internal/config"
	"agentkit/internal/run"
	"agentkit/internal/seat"
)

// evidenced is what watch.health writes onto a seat's login stall each pass that login blocks it:
// what says so, `verb` for its own login out on the answer kept, else `run` for one a run of its
// own waits on (Live.Owed); its signature, the seat's own logout words, else what that answer or
// run said; and the screen it was read on, a blank one keeping the last.  Whether that changed it.
func evidenced(stall *run.Object, live seat.Live, blocked seat.Owed, evidence string) bool {
	before := stall.Copy()
	signature := live.Login
	if signature == nil {
		signature = blocked.Why
	}
	stall.Set("evidence", evidence)
	stall.Set("signature", signature)
	if strings.TrimFunc(live.Pane, config.Space) != "" {
		stall.Set("pane", live.Pane)
	}
	return !run.Equal(before, stall)
}

// keepStanding is what this pass changed at a seat whose login stall stands, written into
// watch.json under its lock before the seat's word reads it: the answer kept of its own login, and
// its stall as this pass read it (evidenced).  A dry tick writes nothing.  False, nothing written,
// where watch.json holds a newer generation of the seat, or what Go cannot write back.
func (t *ticking) keepStanding(live seat.Live) (bool, error) {
	if t.dry {
		return true, nil
	}
	kept := false
	err := locked(func() error {
		current, ok := loadState()
		if !ok || current.Has("auth_out") && current.Dict("auth_out") == nil {
			return nil
		}
		seen, _ := run.Num(current.Dict("seen_at").Get(live.Name))
		before, _ := run.Num(t.state.Dict("seen_at").Get(live.Name))
		if seen > before {
			return nil
		}
		if answers := t.state.Dict("auth_out"); answers != nil && answers.Has(live.Own) {
			if current.Dict("auth_out") == nil {
				current.Set("auth_out", run.NewObject())
			}
			current.Dict("auth_out").Set(live.Own, answers.Get(live.Own))
		}
		current.Dict("stalls").Set(live.Name, t.state.Dict("stalls").Get(live.Name))
		kept = true
		return writeState(current)
	})
	return kept, err
}
