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
// and typed alone into its seat (livePass).
func LiveLeft(record *run.Object) bool {
	_, left := livePass(record)
	return !record.Truthy("live_notified") && left
}

// Live is a merge gone live at `at`, as Python's live_passed tells it under the run's delivery
// lock, on the attempt snapshot is of and not told yet: said by its ending's own line, riding on
// its seat's next prompt, or written down and never typed (livePass).  Untold where LiveLeft holds
// by then: the next tick, reading it owed before it writes, hands it over.  A dry tick decides the
// same, takes no lock and writes nothing: it says what it would record.
func Live(dir string, snapshot *run.Object, at float64, say func(string), dry bool) error {
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
	if recorded, left := livePass(current); left || !recorded {
		return nil
	}
	if dry {
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
