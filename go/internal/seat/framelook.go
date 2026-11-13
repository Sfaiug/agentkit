package seat

import (
	"errors"
	"io/fs"
	"path/filepath"
	"slices"
	"time"

	"agentkit/internal/config"
	"agentkit/internal/plan"
	"agentkit/internal/run"
)

// A glance is a frame's one look at a seat whose panes run on, before anything is written: the
// capture of its screen where Go reads it, what that capture found against its seat file, and
// whether a client is attached.
type glance struct {
	pane             string
	exited, attached bool
	found            sight
	previous         *run.Object
}

// look is a frame's look at each seat whose panes run on, writing nothing: each one's seat file as
// it stands, one capture of its screen and its word decided from them.  ErrUnread where one is
// Python's to answer, or on the ak screen to draw.
func (home Home) look(now float64) ([]glance, error) {
	state := filepath.Join(config.Home(), "state")
	seen := make([]glance, len(home.Seats))
	for at := range home.Seats {
		if !home.Seats[at].live {
			continue
		}
		var err error
		if seen[at], err = home.Seats[at].glanced(state, now, home.drawn); err != nil {
			return nil, err
		}
	}
	return seen, nil
}

func (seat *Seat) glanced(state string, now float64, drawn bool) (glance, error) {
	var seen glance
	if !seat.stands(state, now) {
		return seen, ErrUnread
	}
	if seat.looked() {
		seen.pane, seen.exited, seen.attached = harnessLook(seat.Name)
		seen.found, seen.previous = observed(state, seat.Name, seat.reader, seen.pane, now)
		if seen.exited { // the error it was retrying past ended with it (keepExited)
			seen.found.stall, seen.found.login = nil, nil
		}
	}
	if err := seat.decided(state, seen.found, now, seen.attached); err != nil {
		return seen, err
	}
	// when one out of usage comes back, and the model it could go on with, are Python's to draw
	if drawn && seat.Word == "out of usage" {
		return seen, ErrUnread
	}
	return seen, nil
}

// stands is whether the seat file, as it stands, is still one Go reads by the rule its reading took
// the seat by: a bare seat's (bareSeat), else one a record keeps whose panes run on (read, reading).
func (seat Seat) stands(state string, now float64) bool {
	file, known := seatRead(state, seat.Name)
	if seat.looked() {
		closed, read := waitingStopped(file)
		known = known && read && !closed
	} else {
		known = known && bareFile(file)
	}
	return known && climbingOf(state, seat, sight{}, now).readable()
}

// seatRead is a seat's file, nil for none, and whether Go reads it: an object whose every field
// some reading knows.
func seatRead(state, name string) (*run.Object, bool) {
	file, err := run.Shared(filepath.Join(state, "seat-"+name+".json"))
	return file, errors.Is(err, fs.ErrNotExist) || err == nil && file != nil && only(file, slices.Concat(seatFields, lookFields))
}

// announceLive is watch.announce_state with its look over each seat whose panes run on, from the
// home its frame read.  Every one of their announce locks is held from the first look to the last
// word, taken in name order so no two frames wait on each other: a seat Go leaves to Python refuses
// the frame before any seat is written, and no word lands from a capture older than one another
// announcer published.  Under them the seats look their plans up through the rename pointers as
// they stand then, followed once for all of them, never as the reading found them.
func (home Home) announceLive(state string) error {
	var names []string
	for _, seat := range home.Seats {
		if seat.live {
			names = append(names, seat.Name)
		}
	}
	slices.Sort(names)
	return announcingAll(state, names, func() error {
		plans := plan.OneLook()
		for at := range home.Seats {
			if home.Seats[at].live {
				home.Seats[at].plans = plans
			}
		}
		now := time.Now()
		seen, err := home.look(seconds(now))
		if err != nil {
			return err
		}
		for at := range home.Seats {
			if home.Seats[at].live {
				if err := home.Seats[at].told(state, seen[at], now, home.models); err != nil {
					return err
				}
			}
		}
		return nil
	})
}

func announcingAll(state string, names []string, tell func() error) error {
	if len(names) == 0 {
		return tell()
	}
	return announcing(state, names[0], func() error { return announcingAll(state, names[1:], tell) })
}

// told is a glance kept as watch.look_at keeps it, what the seat kept back asked, and its word
// decided again from what that left and published.
func (seat *Seat) told(state string, seen glance, now time.Time, models map[string]config.Model) error {
	found := seen.found
	if seat.looked() {
		if err := seat.keepHolds(state, found); err != nil {
			return err
		}
		var err error
		if found, err = seat.keep(state, seen.pane, seen.exited, found, seen.previous, seconds(now)); err != nil {
			return err
		}
	}
	if err := seat.askKeptBack(found); err != nil {
		return err
	}
	if err := seat.decided(state, found, seconds(now), seen.attached); err != nil {
		return err
	}
	return seat.announced(state, now, models)
}
