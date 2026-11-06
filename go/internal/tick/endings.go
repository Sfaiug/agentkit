package tick

import (
	"sort"

	"agentkit/internal/handback"
	"agentkit/internal/loop"
	"agentkit/internal/run"
	"agentkit/internal/seat"
)

func (t *ticking) endingsIdle() bool { return true } // this real row reads at its step

// endings is offer_endings: decisions first, through the run's own hand-back, then each merge
// question the inbox still owes. Cleanup and orphan recovery remain Python's, but for the card of
// a seat nothing is left of (handback.Orphaned); a busy seat leaves its mark pending.
func (t *ticking) endings() error {
	type ending struct {
		dir    string
		record *run.Object
	}
	var owed []ending
	carried := run.Every(func(dir string, record *run.Object) bool {
		if run.Active(record) {
			return goingOn(record, epoch(t.clock()))
		}
		if record.Truthy("handback_typed") {
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
		// launched from no seat, a run has nobody to hand its ending back to (handback.announce)
		told := handback.Awaiting(record, t.clock()) && (run.Seat(record) != "" || !run.Ended(record))
		if told && !seat.Watching(run.Seat(record)) && !handback.Orphaned(record) {
			return false
		}
		if told || run.Ended(record) && record.Truthy("pending_inbox") {
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
		current, _ := run.Read(each.dir)
		if current != nil && current.Truthy("handback_typed") {
			return errLeft // this offer's text arrived, but its Enter did not
		}
		if current != nil && handback.Awaiting(current, t.clock()) && handback.Orphaned(current) {
			return errLeft // its card was not Go's to send, or not accepted
		}
		if current != nil && run.Ended(current) && current.Truthy("pending_inbox") &&
			!handback.AskAgain(each.dir, current, t.log.line, t.log.errOut) {
			return errLeft
		}
	}
	return nil
}
