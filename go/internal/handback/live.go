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
// and its seat owes work, which may make the pass its to hear, or a line typed for it waits for
// its Enter.
func LiveLeft(record *run.Object) bool {
	if record.Truthy("live_notified") {
		return false
	}
	if session := run.Seat(record); session != "" {
		if owes, err := plan.Owes(session); owes || err != nil {
			return true
		}
	}
	typed := record.Dict("live_typed")
	return typed != nil && typed.Truthy("line")
}

// Live is a merge gone live at `at`, as Python's live_passed tells it under the run's delivery
// lock, on the attempt snapshot is of and not told yet: written down and never typed.  Left where
// LiveLeft holds by then.
func Live(dir string, snapshot *run.Object, at float64, say func(string)) (left bool, err error) {
	held, err := lock.Wait(context.Background(), filepath.Join(dir, "delivery.lock"))
	if err != nil {
		return false, err
	}
	defer held.Close()
	current, _ := run.Read(dir)
	if current == nil || !sameAttempt(snapshot, current) || current.Truthy("live_notified") {
		return false, nil
	}
	if LiveLeft(current) {
		return true, nil
	}
	if !mark(dir, current, "live_notified", run.Float(at), "live_typed", nil, "live_note", routine) {
		return false, errUnrecorded // the next tick tells it again
	}
	say(fmt.Sprintf("run %s is live: %s. Recorded, not typed", filepath.Base(dir), run.Text(current.Get("pr"))))
	return false, nil
}
