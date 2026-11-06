package seat

import (
	"time"

	"agentkit/internal/config"
)

// heldAgain is watch.announce_state with `look` for a seat tmux holds with its panes all dead, at
// that place on the menu: under its announce lock the ladder its reading climbed is climbed again,
// on what the home holds once the lock is taken and with the runs that reading found, and that word
// is the one saved, put on its bar and printed.  So a word another announcer published while this
// one queued is never overwritten by one decided before.  ErrUnread, the seat unwritten, where the
// ladder cannot decide it there.
func (seat *Seat) heldAgain(state string, place int, models map[string]config.Model) error {
	return announcing(state, seat.Name, func() error {
		now := time.Now()
		if seat.goneAt(state, place, now) != nil {
			return ErrUnread
		}
		return seat.announced(state, now, models)
	})
}
