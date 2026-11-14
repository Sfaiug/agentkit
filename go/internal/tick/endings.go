package tick

import (
	"cmp"
	"slices"
	"sort"

	"agentkit/internal/handback"
	"agentkit/internal/loop"
	"agentkit/internal/run"
)

func (t *ticking) endingsIdle() bool { return true } // this real row reads at its step

// endings is offer_endings: decisions first, through the run's own hand-back, then each merge
// question the inbox still owes. A dead running loop's reap and an interrupted one's sweep are
// written once every offer is known to be Go's, before any is made. Other cleanup and orphan
// recovery remain Python's, but for the card of a seat nothing is left of (handback.Orphaned); a
// busy seat leaves its mark pending.
func (t *ticking) endings() error {
	type ending struct {
		dir    string
		record *run.Object
	}
	var owed []ending
	var census []*run.Object // this pass's one read of every run, each offer's other runs
	var told []*run.Object   // each ending owed a seat, asked whether Go reaches it once census is whole
	var reaps []ending       // dead loops, each in the census as its reap leaves it
	var sweeps []string
	now := epoch(t.clock())
	carried := run.Every(func(dir string, record *run.Object) bool {
		reaped := reapable(record, now)
		if reaped {
			reaps = append(reaps, ending{dir, record})
			record = interrupted(record.Copy(), now)
		}
		census = append(census, record)
		if run.Active(record) {
			return run.GoesOn(record, now)
		}
		if record.Truthy("handback_typed") {
			// Python finishes an existing line's Enter; Go must not leave it blocking the composer.
			return false
		}
		if record.Str("state") == "stalled" {
			return true // parked by the tick: handback.reap leaves it be, and only a resume moves it
		}
		if !run.Ended(record) && run.NeedsRecovery(record) && !handback.Untold(record) && (record.Str("state") != "interrupted" || run.ProcessActive(record)) {
			return false
		}
		// the loop a reap found dead is swept at the next one, as Python's reap sweeps only what it
		// read interrupted
		if record.Str("state") == "interrupted" && (record.Get("pid") != nil || record.Get("scope") != nil) &&
			!run.Equal(record.Get("tree_stopped"), []any{record.Get("pid"), record.Get("process_identity")}) && !reaped {
			if !handback.Sweepable(record) {
				return false // Python still has this interrupted loop's processes to reap
			}
			sweeps = append(sweeps, dir)
		}
		if _, sweep := run.Reap(record); sweep {
			return false
		}
		// launched from no seat, a run has nobody to hand its ending back to (handback.announce)
		owes := handback.Awaiting(record, t.clock()) && (run.Seat(record) != "" || !run.Ended(record))
		if owes {
			told = append(told, record)
		}
		if owes || run.Ended(record) && record.Truthy("pending_inbox") {
			owed = append(owed, ending{dir, record})
		}
		return true
	})
	if !carried || slices.ContainsFunc(told, func(record *run.Object) bool { return !handback.Reaches(record, census) }) {
		return errLeft
	}
	for _, each := range reaps {
		if err := reap(each.dir, each.record, now); err != nil {
			return err
		}
	}
	for _, dir := range sweeps {
		if swept, err := handback.Sweep(dir); err != nil || !swept {
			return cmp.Or(err, errLeft)
		}
	}
	sort.SliceStable(owed, func(i, j int) bool { return !owed[i].record.Truthy("merged") && owed[j].record.Truthy("merged") })
	for _, each := range owed {
		if err := loop.OfferEnding(each.dir, census, t.log.line); err != nil {
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
