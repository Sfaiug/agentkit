package loop

import (
	"agentkit/internal/gh"
	"agentkit/internal/run"
)

// A pull request reviewed with review off is a delivery, Python's review_pr_round and
// settle_pr_round for `off`: no reviewer, its checks are its verdict (judgeOnChecks), nothing is
// posted on GitHub, and a PASS lands it as a seat's own lands (ownPull), somebody else's too, its
// suite run at that landing, or in its round where it was launched with --no-merge.

// lands is whether a PASS of the pull request the record reviews lands it, Python's `is_own or off`.
func lands(record *run.Object) bool {
	return record.Truthy("own_pr") || record.Truthy("review_pr") && run.ReviewOff(record)
}

// pullChecks is a review's checks: the repository's suite, run once at landing where deferred.
func pullChecks(tests string, deferred bool) []string {
	switch {
	case tests == "":
		return nil
	case deferred:
		return []string{tests + "  # once"}
	}
	return []string{tests}
}

// held is the repository's once the checkout is back on the head the review judges, Python's
// restore_review_checkout(lp, "tests"): a suite may regenerate tracked files.
func (p *pullPlace) held(l *loop) (bool, []any, error) {
	if err := p.restore(l, "tests"); err != nil {
		return false, nil, err
	}
	return p.repoPlace.held(l)
}

// published is post's, but with review off nothing is posted and the checks' verdict stands.
func (p *pullPlace) published(l *loop, pull *gh.Pull, record *run.Object) (bool, string, error) {
	if l.alone {
		return true, "", nil
	}
	return p.post(l, pull, record)
}
