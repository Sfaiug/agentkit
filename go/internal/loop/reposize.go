package loop

import (
	"cmp"

	"agentkit/internal/config"
	"agentkit/internal/run"
	"agentkit/internal/size"
)

// worked refuses a change past the first review's ceiling before its checks.
func (r *repoPlace) worked(l *loop) error { return r.firstReviewCeiling(l) }

func (r *repoPlace) beforeReview(l *loop) error { return r.firstReviewCeiling(l) }

// firstReviewDue is whether the change still waits for its first review, the one review its size
// is counted for: once a review of it handed in a verdict, in this run or one it was launched
// `from:`, a later one reviews whatever the fix left.
func (r *repoPlace) firstReviewDue(l *loop) bool {
	record, _ := run.Read(l.dir)
	return record == nil || !run.ChangeReviewed(record)
}

// firstReviewCeiling ends the run blocked with `split it` where its first review would read more
// than `review_lines` added lines, before the reviewer reads a line; the branch it keeps holds the
// work for the pieces.
func (r *repoPlace) firstReviewCeiling(l *loop) error {
	if !r.firstReviewDue(l) {
		return nil
	}
	if err := r.commitLeftovers(l); err != nil {
		return err
	}
	if err := r.followTarget(l); err != nil {
		return err
	}
	why, err := size.Refusal(r.git(), "The change on "+cmp.Or(r.branch, "its branch"), r.baseSHA, "HEAD", l.reviewLines)
	if why == "" || err != nil {
		return err
	}
	return &blocked{why, "## Blocked\n\n" + why}
}

// numbersOf is the first review's ceiling the run holds to (run.Policy), ak's default where that
// does not read.
func numbersOf(record *run.Object) config.Lines {
	numbers, err := run.Policy(record)
	if err != nil {
		return config.AtMost(config.DefaultReviewLines)
	}
	return numbers.ReviewLines
}
