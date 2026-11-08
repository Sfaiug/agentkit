package handback

import (
	"context"
	"errors"
	"fmt"
	"path/filepath"

	"agentkit/internal/lock"
	"agentkit/internal/plan"
	"agentkit/internal/run"
)

var errUnrecorded = errors.New("its live notice could not be written down")

// LiveLeft is whether telling that the merged run `record` went live is Python's: not told yet,
// and its seat owes work, which may make the pass its to hear, unless its ending's own line says it
// (carries); or a line typed for it waits for its Enter.
func LiveLeft(record *run.Object) bool {
	if record.Truthy("live_notified") {
		return false
	}
	if session := run.Seat(record); session != "" {
		if owes, err := plan.Owes(session); owes || err != nil {
			carried, _ := carries(record)
			return !carried
		}
	}
	typed := record.Dict("live_typed")
	return typed != nil && typed.Truthy("line")
}

// Live is a merge gone live at `at`, as Python's live_passed tells it under the run's delivery
// lock, on the attempt snapshot is of and not told yet: said by its ending's own line, or written
// down and never typed.  Untold where LiveLeft holds by then: the next tick, reading it owed before
// it writes, hands it over.  A dry tick decides the same, takes no lock and writes nothing: it says
// what it would record.
func Live(dir string, snapshot *run.Object, at float64, say func(string), dry bool) error {
	if !dry {
		held, err := lock.Wait(context.Background(), filepath.Join(dir, "delivery.lock"))
		if err != nil {
			return err
		}
		defer held.Close()
	}
	current, _ := run.Read(dir)
	if current == nil || !sameAttempt(snapshot, current) || current.Truthy("live_notified") || LiveLeft(current) {
		return nil
	}
	if carried, _ := carries(current); carried {
		return nil // the ending's line, typed later in this tick, says it
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
