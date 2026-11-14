package loop

import (
	"fmt"
	"strconv"

	"agentkit/internal/run"
)

// judgeOnChecks is the review of a run with review off, Python's review there: no reviewer, the
// checks are the verdict.  It passes where they passed on the commit they ran on, which the
// checkout still holds with nothing uncommitted, and the record's review says so in place of a
// reviewer's evidence (run.ReviewPass).  A base proof the record owes runs first, as beside a review.
func (l *loop) judgeOnChecks(ok bool, checked string) (bool, error) {
	proof, err := l.place.baseProof(l, ok)
	if err != nil {
		return false, err
	}
	defer proof.drop()
	if err := l.proven(proof); err != nil {
		return false, err
	}
	held, evidence, err := l.place.held()
	if err != nil {
		return false, err
	}
	ok = ok && held
	verdict, findings, word := "PASS", "", "passed"
	if !ok {
		verdict, findings, word = "FAIL", checked, "FAILED"
	}
	review := run.Fields("no_review", true, "executor", l.executor, "reviewer", nil, "verdict", verdict, "returncode", 0, "done_when", ok)
	run.SetAll(review, evidence...)
	if err := l.save(func(record *run.Object) {
		run.SetAll(record, "verdict", verdict, "findings", findings, "review", review)
		record.Delete("review_pending")
	}); err != nil {
		return false, err
	}
	l.say("no review: checks " + word)
	return ok, nil
}

// held is whether the checkout still holds the commit the round's checks ran on, with nothing
// uncommitted, and that commit as evidence.
func (r *repoPlace) held() (bool, []any, error) {
	head, tree := r.checked[0], r.checked[1]
	moved, err := r.changedSince(head, tree)
	return !moved, []any{"head_sha", head, "tree_sha", tree}, err
}

// held is a workspace's: it has no commit for its checks to have run on.
func (scratch) held() (bool, []any, error) { return true, nil, nil }

// staffed is the log's line of who works the run.
func (l *loop) staffed(rounds int) string {
	if l.alone {
		return "executor=" + l.executor + " no review"
	}
	return fmt.Sprintf("executor=%s reviewer=%s rounds=%d", l.executor, l.reviewer, rounds)
}

// roundsLine is a result's line of the rounds the run spent of its budget.
func roundsLine(record *run.Object) string {
	if run.ReviewOff(record) {
		return "no review"
	}
	return "rounds: " + strconv.Itoa(len(record.List("round_summaries"))) + " of " + run.Field(record, "rounds", "None")
}

// reviewedBy is who reviewed the run, as its result names them.
func reviewedBy(record *run.Object) string {
	if run.ReviewOff(record) {
		return "no review"
	}
	return run.Field(record, "reviewer", "None")
}
