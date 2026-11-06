package tick

import (
	"io"
	"slices"

	"agentkit/internal/run"
	"agentkit/internal/seat"
	"agentkit/internal/tmux"
)

// auditUp is whether the seat is orch.find's on ak's own server and has not exited.
func auditUp(name string) bool {
	own := tmux.Own()
	held := slices.ContainsFunc(tmux.Sessions(own), func(session tmux.Session) bool { return session.Name == name })
	return held && !slices.Contains(tmux.Dead(own), name)
}

// leftTyped is a line typed into the seat whose delivery is Python's: one in a seat not up, whose
// composer a reopened seat no longer holds, or one ak's editor took in, its receipt naming the pane.
func leftTyped(name string, state *run.Object) bool {
	typed := state.Dict("typed")
	return state.Truthy("typed") && (typed != nil && typed.Has("pane") || !auditUp(name))
}

// tellAudit is watch.tell_audit for an audit seat with a record: one whose harness is gone comes
// back on its own conversation, as its number opens it (orch.ensure with `saved`), and a later tick
// types the line once it sits at its prompt.  The line goes in at its quiet prompt, its receipt
// kept in the week's state, and is delivered once its composer reads empty; a harness Go does
// not type into is Python's.
func (t *ticking) tellAudit(name string, state *run.Object, write func() error) error {
	if !auditUp(name) {
		opened, err := seat.Reopen(name, seat.How{}, io.Discard, io.Discard)
		if err == nil && !opened {
			return errLeft
		}
		return err
	}
	if !seat.Typable(name) {
		return errLeft
	}
	var kept error
	if !seat.TypeAtPrompt(name, state.Str("line"), state.Dict("typed"), func(mark *run.Object) error {
		state.Set("typed", mark)
		kept = write()
		return kept
	}, t.log.line) {
		return kept
	}
	state.Set("delivered", run.Float(epoch(t.clock())))
	if err := write(); err != nil {
		return err
	}
	t.log.line("audit: told the " + name + " seat about week " + state.Str("week"))
	return nil
}
