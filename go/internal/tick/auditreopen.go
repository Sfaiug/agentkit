package tick

import (
	"io"
	"slices"

	"agentkit/internal/seat"
	"agentkit/internal/tmux"
)

// reopenAudit is watch.tell_audit for an audit seat with a record: one whose harness is gone comes
// back on its own conversation, as its number opens it (orch.ensure with `saved`), and a later tick
// types the line once it sits at its prompt; typing into one that is up is Python's.
func reopenAudit(name string) error {
	own := tmux.Own()
	held := slices.ContainsFunc(tmux.Sessions(own), func(session tmux.Session) bool { return session.Name == name })
	if held && !slices.Contains(tmux.Dead(own), name) {
		return errLeft
	}
	opened, err := seat.Reopen(name, seat.How{}, io.Discard, io.Discard)
	if err == nil && !opened {
		return errLeft
	}
	return err
}
