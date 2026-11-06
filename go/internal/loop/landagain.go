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
