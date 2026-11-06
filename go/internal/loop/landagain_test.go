//go:build linux

package loop

import (
	"strings"
	"testing"

	"agentkit/internal/run"
)

// A landing's review cut off before its conflict was fixed meets a target that moved clean past
// the conflict: its pending review stays as it was, no review saved before stands for the new
// commit, and the checks run again in that review's round before any reviewer reads it.
func TestALandingReviewOnACleanRebaseIsCheckedAgainInItsOwnRound(t *testing.T) {
	l, r := repoRig(t)
	shell(t, r.repo, "git remote add origin "+r.repo)
	shell(t, r.wt, "echo own > own.txt; git add -A; git commit -qm own")
	pending := run.Fields("round", 1, "record", false, "summary", "the work", "reason", "Re-review after the rebase of origin/main.", "since", "s1")
	if err := run.Change(l.dir, func(record *run.Object) error {
		run.SetAll(record, "base", "main", "target", "main", "base_sha", r.baseSHA, "review_pending", pending.Copy())
		return nil
	}); err != nil {
		t.Fatal(err)
	}
	shell(t, r.repo, "echo ahead > ahead.txt; git add -A; git commit -qm ahead")
	l.rnd, l.every = 2, []string{"test -f nothing.txt"}
	_, err := r.integrate(l, "origin/main")
	if err == nil || !strings.Contains(err.Error(), "a fixer at landing is not Go's yet") {
		t.Fatalf("integrate: %v", err)
	}
	record, _ := run.Read(l.dir)
	if !run.Equal(record.Get("review_pending"), pending) || record.Get("review") != nil || l.rnd != 1 {
		t.Fatalf("pending %s, review %v, round %d", run.Line(record.Dict("review_pending")), record.Get("review"), l.rnd)
	}
	if shell(t, r.wt, "git log --format=%s -1 HEAD~1") != "ahead\n" {
		t.Fatal("the branch is not on the target's tip")
	}
}
