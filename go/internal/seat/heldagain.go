package seat

import (
	"slices"
	"time"
)

// heldAgain is watch.announce_state with `look` for a seat tmux holds with its panes all dead: under
// its announce lock the home is read again, with the runs the first reading found, and the word that
// reading's ladder gives the seat is the one saved, put on its bar and printed.  So a word another
// announcer published while this one queued is never overwritten by one decided before, nor from
// marks that moved meanwhile.  ErrUnread, the seat unwritten, where that reading does not know the
// home or no longer finds the seat held with its panes all dead.
func (seat *Seat) heldAgain(state string, home Home) error {
	return announcing(state, seat.Name, func() error {
		now := time.Now()
		found := func([]string, time.Time) (map[string][]ran, bool) { return home.found, true }
		again, known := reading(now, true, found, home.readers)
		at := slices.IndexFunc(again.Seats, func(each Seat) bool { return each.Name == seat.Name })
		if !known || at < 0 || !again.Seats[at].held {
			return ErrUnread
		}
		*seat = again.Seats[at]
		return seat.announced(state, now, again.models)
	})
}
