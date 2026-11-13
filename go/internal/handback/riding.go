package handback

import (
	"cmp"
	"errors"
	"os"
	"path/filepath"
	"slices"

	"agentkit/internal/lock"
	"agentkit/internal/run"
	"agentkit/internal/seat"
)

// rider is a run of the seat whose news its prompt carries, as decided under its delivery lock: its
// ending, saying its change went live too where `live`, and its change going live told alone.
type rider struct {
	dir                 string
	said                *run.Object
	ending, live, alone bool
}

// ridingLine is a line a prompt carries, at the time it orders by.
type ridingLine struct {
	at   float64
	line string
}

// Riding decides what a prompt starting a turn in the seat `session` carries of its runs, as
// Python's handback.riding tells it, and tell tells it, oldest first, each marked told: every
// ending waiting for the seat (Waiting) and not held for its change going live, saying it went live
// too where that ends the seat's wait, and each merged change gone live the seat is still owed in no
// line already in a composer.  The prompt never waits: a run whose delivery lock is held is being
// told this moment, perhaps as this very prompt, and is passed over, as is one moved on or
// unreadable, and one whose record cannot be written now stays owed.  Every run is decided, under
// its lock, before tell writes anything, so an error, where Go cannot decide one as Python does,
// writes nothing and holds nothing.
func Riding(session string) (tell func() string, err error) {
	var riders []rider
	var locks []*os.File
	release := func() {
		for _, held := range locks {
			held.Close()
		}
	}
	defer func() {
		if err != nil {
			release()
		}
	}()
	seatOf := run.Seats()
	for _, dir := range run.Dirs() {
		record, err := run.Read(dir)
		if errors.Is(err, run.ErrLoneSurrogate) {
			return nil, err
		}
		if record == nil || !record.Truthy("handback_pending") && !(record.Truthy("live_at") && !record.Truthy("live_notified")) ||
			seatOf(record) != session {
			continue
		}
		held, err := lock.Try(filepath.Join(dir, "delivery.lock"))
		if err != nil {
			continue
		}
		locks = append(locks, held)
		said, err := run.Read(dir)
		if errors.Is(err, run.ErrLoneSurrogate) {
			return nil, err
		}
		if said == nil || !sameAttempt(record, said) {
			continue
		}
		each := rider{dir: dir, said: said, ending: Waiting(said)}
		if each.ending {
			holds, carries, err := liveEnding(said, nil)
			if err != nil {
				return nil, err
			}
			each.ending = !holds
			if each.ending && carries {
				if each.live, err = seat.EndsWait(session, nil, said); err != nil {
					return nil, err
				}
			}
		}
		if !each.live && said.Truthy("live_at") && !said.Truthy("live_typed") {
			if each.alone, _, err = liveOwed(said, nil); err != nil {
				return nil, err
			}
		}
		riders = append(riders, each)
	}
	return func() string {
		defer release()
		return told(riders)
	}, nil
}

// told is the text telling each rider, those marked told.
func told(riders []rider) string {
	var lines []ridingLine
	for _, each := range riders {
		if each.ending {
			// an ending not told, its line not fitting or its record busy, leaves the run waiting, its
			// change going live with it: that is never told before the merge it follows
			line := handbackLine(each.said, each.dir, true, each.live)
			if line == "" || !markBy(run.DeliverNow, each.dir, each.said, toldMarks(saidLive(each.live, "live_notified", now()))...) {
				continue
			}
			at, _ := each.said.Num("finished_at")
			lines = append(lines, ridingLine{at, line})
		}
		if each.alone {
			line := seatNotice(each.said, each.dir, liveSentence(each.said, each.dir), "run "+filepath.Base(each.dir)+" is live.",
				"Decide the next step.", true)
			if line != "" && markBy(run.DeliverNow, each.dir, each.said, "live_notified", now()) {
				at, _ := each.said.Num("live_at")
				lines = append(lines, ridingLine{at, line})
			}
		}
	}
	if len(lines) == 0 {
		return ""
	}
	slices.SortStableFunc(lines, func(a, b ridingLine) int { return cmp.Compare(a.at, b.at) })
	text := "Runs you have not been told about yet:"
	for _, each := range lines {
		text += "\n" + each.line
	}
	return text
}
