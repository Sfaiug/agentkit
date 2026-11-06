package tick

import (
	"sort"

	"agentkit/internal/handback"
	"agentkit/internal/loop"
	"agentkit/internal/run"
	"agentkit/internal/seat"
)

func (t *ticking) endingsIdle() bool { return true } // this real row reads at its step

// endings is offer_endings: decisions first, through the run's own hand-back. Cleanup,
// orphan recovery and inbox questions remain Python's; a busy seat leaves its mark pending.
func (t *ticking) endings() error {
	type ending struct {
		dir    string
		record *run.Object
	}
	var owed []ending
	carried := run.Every(func(dir string, record *run.Object) bool {
		if run.Active(record) {
			return run.ProcessActive(record) || launchGrace(record, epoch(t.clock())) || resumeOrdered(record, epoch(t.clock()))
		}
		if record.Truthy("pending_inbox") || record.Truthy("handback_typed") {
			// Python finishes an existing line's Enter; Go must not leave it blocking the composer.
			return false
		}
		if !run.Ended(record) && run.NeedsRecovery(record) && (record.Str("state") != "interrupted" || run.ProcessActive(record)) {
			return false
		}
		if record.Str("state") == "interrupted" && (record.Get("pid") != nil || record.Get("scope") != nil) &&
			!run.Equal(record.Get("tree_stopped"), []any{record.Get("pid"), record.Get("process_identity")}) {
			return false // Python still has this interrupted loop's processes to reap
		}
		if _, sweep := run.Reap(record); sweep {
			return false
		}
		if handback.Awaiting(record, t.clock()) {
			if run.Ended(record) && run.Seat(record) == "" {
				return true // launched from no seat, it has nobody to hand back to (handback.announce)
			}
			if !seat.Watching(run.Seat(record)) {
				return false
			}
			owed = append(owed, ending{dir, record})
		}
		return true
	})
	if !carried {
		return errLeft
	}
	sort.SliceStable(owed, func(i, j int) bool { return !owed[i].record.Truthy("merged") && owed[j].record.Truthy("merged") })
	for _, each := range owed {
		if err := loop.OfferEnding(each.dir, t.log.line); err != nil {
			return err
		}
		if current, _ := run.Read(each.dir); current != nil && current.Truthy("handback_typed") {
			return errLeft // this offer's text arrived, but its Enter did not
		}
	}
	return nil
}
