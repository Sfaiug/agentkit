package handback

import (
	"context"
	"errors"
	"fmt"
	"path/filepath"

	"agentkit/internal/lock"
	"agentkit/internal/run"
)

var errUnrecorded = errors.New("its live notice could not be written down")

// LiveLeft is whether telling that the merged run `record` went live is Python's: not told yet,
// and a line typed for it waiting for its Enter, or what decides it unread (livePass), its seat's
// other runs read from census.
func LiveLeft(record *run.Object, census []*run.Object) bool {
	return !record.Truthy("live_notified") && livePass(record, census) == liveLeft
}

// Live is a merge gone live at `at`, as Python's live_passed tells it under the run's delivery
// lock, on the attempt snapshot is of and not told yet: said by its ending's own line, riding on
// its seat's next prompt, typed alone into its seat (tellLive), or written down and never typed
// (livePass).  Untold where LiveLeft holds by then: the next tick, reading it owed before it
// writes, hands it over.  Its own record is read again under the lock, and its seat's other runs
// from census.  A dry tick decides the same, takes no lock and writes nothing: it says what it
// would record or tell.
func Live(dir string, snapshot *run.Object, census []*run.Object, at float64, say func(string), dry bool) error {
	if !dry {
		held, err := lock.Wait(context.Background(), filepath.Join(dir, "delivery.lock"))
		if err != nil {
			return err
		}
		defer held.Close()
	}
	current, _ := run.Read(dir)
	if current == nil || !sameAttempt(snapshot, current) || current.Truthy("live_notified") {
		return nil
	}
	switch pass := livePass(current, census); {
	case pass == liveTyped:
		return tellLive(dir, current, at, say, dry)
	case pass != liveRecorded:
		return nil
	case dry:
		say("would record, not type: " + liveSentence(current, dir))
		return nil
	}
	if !mark(dir, current, "live_notified", run.Float(at), "live_typed", nil, "live_note", routine) {
		return errUnrecorded // the next tick tells it again
	}
	say(liveSentence(current, dir) + " Recorded, not typed")
	return nil
}

// liveSentence is the whole notice that a merge went live (handback.live_sentence).
func liveSentence(record *run.Object, dir string) string {
	return fmt.Sprintf("run %s is live: %s.", filepath.Base(dir), run.Text(record.Get("pr")))
}
