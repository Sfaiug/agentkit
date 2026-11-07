package seat

import (
	"slices"
	"time"
)

// heldAgain is watch.announce_state with `look` for a seat tmux holds with its panes all dead: under
// its announce lock the home is read again, with the run records the first reading found judged by
// the clock read there, and the word that reading's ladder gives the seat is the one saved, put on
// its bar and printed.  So a word another announcer published while this one queued is never
// overwritten by one decided before, from marks that moved meanwhile, or by a clock a run's window
// has passed; a run that moved meanwhile moves nothing, as Python's caller hands its records down.
// ErrUnread, the seat unwritten, where that reading does not know the home or no longer finds the
// seat held with its panes all dead.
func (seat *Seat) heldAgain(state string, home Home) error {
	return announcing(state, seat.Name, func() error {
		now := time.Now()
		again, known := reading(now, true, func([]string) judges { return home.found }, home.readers)
		at := slices.IndexFunc(again.Seats, func(each Seat) bool { return each.Name == seat.Name })
		if !known || at < 0 || !again.Seats[at].held {
			return ErrUnread
		}
		*seat = again.Seats[at]
		return seat.announced(state, now, again.models)
	})
}

// handBacks is how many of a seat's own runs wait to hand back, which the reason of one the owner
// closed counts (watch._session_state's rung 4).
func handBacks(mine []ran) int {
	waiting := 0
	for _, each := range mine {
		if each.record.Truthy("handback_pending") {
			waiting++
		}
	}
	return waiting
}
