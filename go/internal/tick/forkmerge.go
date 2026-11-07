package tick

import (
	"errors"
	"path/filepath"

	"agentkit/internal/handback"
	"agentkit/internal/loop"
	"agentkit/internal/run"
)

// A maintainer's merge of a pull request ak opened from a fork is routine, as in Python's say: it
// is recorded on the run that opened it (recordDecision), and typed into no seat where the run's
// ending is never typed (handback.Untyped).  The run then keeps the merge's notice as its
// hand-back, offered as any ending is.  Where its seat owes work for it, it is typed as a decision
// is.

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

// endRoutine ends the following of a routine merge: a line an earlier decision left unsent in
// the seat's composer gets its Enter first, and the run keeps the merge's notice as its fresh
// hand-back, offered as any ending is while it is owed (loop.OfferEnding).  Said is as say's; a
// hand-back that cannot be written fails the tick, as Python's raise does, and the next one
// writes it.
func (t *ticking) endRoutine(dir string, record *run.Object, notice string) (bool, error) {
	if sent, err := t.sentPending(dir, record); !sent || dir == "" {
		return sent, err
	}
	// once: a retry after the hand-back was said never makes it owed again
	if !record.Truthy("merge_handback") && !handback.MarkDelivery(dir, record, "merge_handback", notice, "handed_back", nil,
		"reported", false, "handback_pending", nil, "handback_note", nil, "handback_typed", nil, "handback_wait_reason", nil,
		"notification_pending", nil) {
		return false, errors.New("run " + filepath.Base(dir) + ": the merge's hand-back could not be written")
	}
	if err := loop.OfferEnding(dir, t.log.line); err != nil {
		return false, err
	}
	return true, nil
}
