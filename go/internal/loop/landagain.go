package loop

import (
	"cmp"
	"errors"

	"agentkit/internal/run"
)

// landAgain carries on a run cut off with a landing's review pending, Python's rounds on a review
// that is no task round's: the target's tip comes in again, checked and reviewed there, as at its
// landing.  Whether the review passed; a target that cannot be reached is the tick's error retry.
func (l *loop) landAgain(r *repoPlace) (bool, error) {
	integrated, err := r.integrate(l, r.upstream())
	if err != nil {
		return false, err
	}
	record, err := run.Read(l.dir)
	if record == nil {
		return false, cmp.Or(err, errors.New("run.json cannot be read"))
	}
	if !integrated && record.Truthy("merge_failed") {
		return false, errors.New(record.Str("merge_note"))
	}
	return run.ReviewPass(record, run.Models()), nil
}

// landingReview is whether the review pending is a landing's, which spends no round.
func landingReview(record *run.Object) bool {
	pending := record.Dict("review_pending")
	return pending != nil && pending.Get("record") == false
}

// reviewLanding finishes a landing's review on the commit a clean integration made, Python's
// integrate on one: no review saved before it stands for that commit, so the checks run again in
// the pending review's round and that review judges it there.  Whether it passed.
func (r *repoPlace) reviewLanding(l *loop, upstream, how string) (bool, error) {
	pending, err := l.pendingRound()
	if pending == nil {
		return false, cmp.Or(err, errors.New("the landing's pending review is gone"))
	}
	text, err := l.checkedAgain(upstream, how)
	if err != nil {
		return false, err
	}
	passed, err := l.reviewPending(pending, true, text)
	return r.afterReview(l, "the "+how+" of "+upstream, passed, err)
}
