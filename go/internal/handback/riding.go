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

// Riding is what a prompt starting a turn in the seat `session` carries of its runs, as Python's
// handback.riding tells it, oldest first, each marked told: every ending waiting for the seat
// (Waiting) and not held for its change going live, saying it went live too where that ends the
// seat's wait, and each merged change gone live the seat is still owed in no line already in a
// composer.  The prompt never waits: a run whose delivery lock is held is being told this moment,
// perhaps as this very prompt, and is passed over, as is one moved on or unreadable.  Every run is
// decided, under its lock, before anything is written, so an error, where Go cannot decide one as
// Python does, writes nothing.
func Riding(session string) (string, error) {
	var riders []rider
	var locks []*os.File
	defer func() {
		for _, held := range locks {
			held.Close()
		}
	}()
	seatOf := run.Seats()
	for _, dir := range run.Dirs() {
		record, err := run.Read(dir)
		if errors.Is(err, run.ErrLoneSurrogate) {
			return "", err
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
			return "", err
		}
		if said == nil || !sameAttempt(record, said) {
			continue
		}
		each := rider{dir: dir, said: said, ending: Waiting(said)}
		if each.ending {
			holds, carries, err := liveEnding(said, nil)
			if err != nil {
				return "", err
			}
			each.ending = !holds
			if each.ending && carries {
				if each.live, err = seat.EndsWait(session, nil, said); err != nil {
					return "", err
				}
			}
		}
		if !each.live && said.Truthy("live_at") && !said.Truthy("live_typed") {
			if each.alone, _, err = liveOwed(said, nil); err != nil {
				return "", err
			}
		}
		riders = append(riders, each)
	}
	var lines []ridingLine
	for _, each := range riders {
		if each.ending {
			// a line that cannot be told leaves the run waiting, its change going live with it
			line := handbackLine(each.said, each.dir, true, each.live)
			if line == "" {
				continue
			}
			if Told(each.dir, each.said, saidLive(each.live, "live_notified", now())...) {
				at, _ := each.said.Num("finished_at")
				lines = append(lines, ridingLine{at, line})
			}
		}
		if each.alone {
			line := seatNotice(each.said, each.dir, liveSentence(each.said, each.dir), "run "+filepath.Base(each.dir)+" is live.",
				"Decide the next step.", true)
			if line != "" && mark(each.dir, each.said, "live_notified", now()) {
				at, _ := each.said.Num("live_at")
				lines = append(lines, ridingLine{at, line})
			}
		}
	}
	if len(lines) == 0 {
		return "", nil
	}
	slices.SortStableFunc(lines, func(a, b ridingLine) int { return cmp.Compare(a.at, b.at) })
	text := "Runs you have not been told about yet:"
	for _, each := range lines {
		text += "\n" + each.line
	}
	return text, nil
}
