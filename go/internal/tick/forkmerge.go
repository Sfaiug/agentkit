package tick

import (
	"slices"

	"agentkit/internal/handback"
	"agentkit/internal/loop"
	"agentkit/internal/run"
	"agentkit/internal/seat"
)

// A maintainer's merge of a pull request ak opened from a fork is routine, as in Python's say: it
// is recorded on the run that opened it (recordDecision), and typed into no seat where the run's
// ending is recorded and never typed or rides the seat's next prompt (seat.EndingDelivery).  The
// run then keeps the merge's notice as its hand-back, offered as any ending is.  Where its seat
// owes work for it, it is typed as a decision is.

// mergeRecord puts on fields what a merge records on its run, Python's `merged` and merge_record
// for the run's worktree and delivered commit, naming no pull request: the `health:` and
// `deployed:` that commit declares, neither where the worktree lacks it, for the tick's later
// passes to read.
func mergeRecord(record, fields *run.Object) error {
	fields.Set("merged", true)
	if !record.Truthy("worktree") || !record.Truthy("delivery_sha") {
		return nil
	}
	found, err := declared(record.Str("worktree"), record.Str("delivery_sha"), "")
	if err != nil {
		return err
	}
	for _, name := range found.Keys() {
		fields.Set(name, found.Get(name))
	}
	return nil
}

// routine is whether no line is typed for the merge just recorded on the run, its plan checks
// run: its ending is recorded and never typed, or rides the seat's next prompt.  As in Python's
// ends_wait, the run itself is none of the seat's other runs, whose work may end its wait.
func routine(record *run.Object) bool {
	census, _ := run.Records()
	others := slices.DeleteFunc(census, func(other *run.Object) bool { return run.Equal(other.Get("run_id"), record.Get("run_id")) })
	recorded, rides := seat.EndingDelivery(record, others, run.Seat(record))
	return recorded || rides
}

// endRoutine ends the following of a routine merge: a line an earlier decision left unsent in
// the seat's composer gets its Enter first, and the run keeps the merge's notice as its fresh
// hand-back, offered as any ending is while it is owed (loop.OfferEnding).  Said is as say's.
func (t *ticking) endRoutine(dir string, record *run.Object, notice string) (bool, error) {
	if sent, err := t.sentPending(dir, record); !sent || dir == "" {
		return sent, err
	}
	// once: a retry after the hand-back was said never makes it owed again
	if !record.Truthy("merge_handback") {
		handback.MarkDelivery(dir, record, "merge_handback", notice, "handed_back", nil, "reported", false,
			"handback_pending", nil, "handback_note", nil, "handback_typed", nil, "handback_wait_reason", nil,
			"notification_pending", nil)
	}
	if err := loop.OfferEnding(dir, t.log.line); err != nil {
		return false, err
	}
	return true, nil
}
