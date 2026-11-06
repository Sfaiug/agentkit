package seat

import (
	"errors"
	"io/fs"
	"path/filepath"
	"slices"
	"time"

	"agentkit/internal/config"
	"agentkit/internal/run"
	"agentkit/internal/tmux"
)

// A shot is a reading's one capture of a seat whose panes run on (Seat.shot): what its harness's
// pane shows and whether that harness exited, where Go reads its screen, and whether a client is
// attached.  A frame refuses on it before anything is written (Menu) and publishes from it after,
// as Python's pass captures each seat once (menu.v5o_groups).
type shot struct {
	pane             string
	exited, attached bool
}

func (seat Seat) shoot() (taken shot) {
	if seat.looked() {
		taken.pane, taken.exited = harnessScreen(seat.Name)
	}
	attached, _ := tmux.Ask(seat.server(), "display-message", "-p", "-t", "="+seat.Name+":", "#{session_attached}")
	taken.attached = attached != "" && attached != "0"
	return taken
}

// lookedOnce is the look at a seat its panes still run on from the home its frame read, under its
// announce lock: the seat file as it stands there, as watch.announce_state reads watch.seat_read,
// and the rest of the home, its screen among it, as that read found it.
func (seat *Seat) lookedOnce(state string, models map[string]config.Model) error {
	return announcing(state, seat.Name, func() error {
		now := time.Now()
		if !seat.stands(state, seconds(now)) {
			return ErrUnread
		}
		return seat.lookAnnounced(state, now, models)
	})
}

// stands is whether the seat file, as it stands under the announce lock, is still one Go reads of a
// seat whose panes run on (read, reading): what came to it while the look waited, the owner's stop
// among it, is Python's to answer, with nothing written.
func (seat Seat) stands(state string, now float64) bool {
	file, known := seatRead(state, seat.Name)
	closed, read := waitingStopped(file)
	return known && read && !closed && climbingOf(state, seat, sight{}, now).readable()
}

// seatRead is a seat's file, nil for none, and whether Go reads it: an object whose every field
// some reading knows.
func seatRead(state, name string) (*run.Object, bool) {
	file, err := run.ReadJSON(filepath.Join(state, "seat-"+name+".json"))
	return file, errors.Is(err, fs.ErrNotExist) || err == nil && file != nil && only(file, slices.Concat(seatFields, lookFields))
}

// lookAnnounced is watch.announce_state's look, under the seat's announce lock: its reading's
// capture classified and kept, what it kept back asked, its word decided and published.
func (seat *Seat) lookAnnounced(state string, now time.Time, models map[string]config.Model) error {
	taken, found := seat.shot(), sight{}
	if seat.looked() {
		var err error
		if found, err = seat.kept(state, taken.pane, taken.exited, seconds(now)); err != nil {
			return err
		}
	}
	if err := seat.askKeptBack(found); err != nil {
		return err
	}
	if err := seat.decided(state, found, seconds(now), taken.attached); err != nil {
		return err
	}
	return seat.announced(state, now, models)
}
