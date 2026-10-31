package seat

import (
	"cmp"
	"path/filepath"
	"slices"
	"time"

	"agentkit/internal/config"
)

// Explain is Python's orch.explain of the seat by that name, once its listing has written into
// the records what it reconciles and infers and its announce the seat's word: the word, why, and
// that nothing read its screen, Go reading only seats tmux no longer holds; false where no seat
// Go reads goes by that name.
func (home Home) Explain(name string, now time.Time) ([]string, bool, error) {
	state := filepath.Join(config.Home(), "state")
	if err := reconcile(state, home.records, true); err != nil {
		return nil, false, err
	}
	at := slices.IndexFunc(home.Seats, func(seat Seat) bool { return seat.Name == name })
	if at < 0 {
		return nil, false, nil
	}
	seat := home.Seats[at]
	if err := seat.announce(state, now, home.models); err != nil {
		return nil, false, err
	}
	return []string{seat.Name + "  " + seat.Word, "  reason:    " + cmp.Or(seat.reason, "-"),
		"  authority: -     the process is gone; nothing here read its screen"}, true, nil
}
