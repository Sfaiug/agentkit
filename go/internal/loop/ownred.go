package loop

import (
	"cmp"
	"fmt"
	"os"
	"path/filepath"

	"agentkit/internal/run"
)

// A seat's own PR whose suite goes red at its landing goes back to its writer as a finding does,
// Python's fail_pr_landing: the failure joins the run's findings, the writer's model gets a fixer
// turn under a name of its own for each red (fixOwn), its fix a re-review that spends no round
// (ownRound), and a PASS lands the fixed head.  A landing gets conflictRounds reds; past them the
// run fails.

// failLanding is the red handed to the writer, Python's fail_pr_landing for a landing red: the
// record leaves the line on it and waits for the fix, or fails past the bound.
func (p *ownPull) failLanding(l *loop, record, fix *run.Object) error {
	if road := landingFixHandoff(record); road != "" {
		return notYet(fmt.Sprintf("its landing failed: %s; see %s", fix.Str("line"), fix.Str("log")), road)
	}
	output, err := os.ReadFile(fix.Str("log"))
	if err != nil {
		return err
	}
	text := l.findings + "\n\n## Landing failed\n" + decoded(output)
	path := filepath.Join(l.dir, "landing-findings.md")
	if err := os.WriteFile(path, []byte(text), 0o666); err != nil {
		return err
	}
	l.findings, l.findingsFile = text, path
	patch, red, err := p.redPatch(record, fix)
	if err != nil {
		return err
	}
	return l.save(func(record *run.Object) {
		tail := []rune(text)
		review := cmp.Or(record.Dict("review"), run.NewObject())
		run.SetAll(record, "verdict", "FAIL", "findings", string(tail[max(0, len(tail)-8000):]), "findings_file", path,
			"final_check", run.Fields("outcome", "failed", "where", "landing", "line", fix.Get("line"), "log", fix.Str("log")),
			"review", run.SetAll(review, "verdict", "FAIL", "overridden", fix.Get("line")))
		for _, key := range []string{"waiting_on", "own_pr_round_pending", "landing_fix"} {
			record.Delete(key)
		}
		reds, _ := record.Int("landing_reds")
		reds++
		record.Set("landing_reds", reds)
		if red {
			record.Set("landing_red_patches", append(record.List("landing_red_patches"), patch))
		}
		if reds <= conflictRounds {
			run.SetAll(record, "state", "running", "finished_at", nil, "own_pr_wait", record.Get("head_sha"), "landing_fix", true)
			return
		}
		// the counts bound one landing; a person who resumes the ended run starts a new one
		leaveLine(record)
		run.SetAll(record, "merge_note", fmt.Sprintf("landing failed %d times: %s", reds, fix.Str("line")), "state", "fail", "finished_at", clock())
	})
}

// ownFix is the round and the turn the next head of a seat's own PR comes from, which its review
// shares, Python's own_pr_fix: the next round's executor, or a landing red's fixer in the round
// whose PASS it repairs, under a name for each red, so no earlier fixer stands for it.
func ownFix(record *run.Object) (int, string) {
	done := len(record.List("round_summaries"))
	if !record.Truthy("landing_fix") {
		return done + 1, "executor"
	}
	reds, _ := record.Int("landing_reds")
	conflicts, _ := record.Int("landing_conflicts")
	return done, fmt.Sprintf("landing-%d-fixer", reds+conflicts)
}

// landingFixed is whether this round re-reviews a landing fix, Python's review_pr_round: on a head
// the run wrote it spends no round, however the budget stands.  One the seat pushed meanwhile is the
// seat's own, a round, and the mark comes off the record as it stands now.
func (l *loop) landingFixed(prior *run.Object, head string) (bool, error) {
	if !prior.Truthy("landing_fix") {
		return false, nil
	}
	if head == prior.Str("head_sha") || head == prior.Str("delivery_sha") {
		return true, nil
	}
	prior.Delete("landing_fix")
	return false, l.save(func(record *run.Object) { record.Delete("landing_fix") })
}

// offTheLine puts a landing fix's checkout back on the head its review passed, Python's fix_own_pr:
// the line left it on its rebase onto the target, which the next landing makes again.
func (p *ownPull) offTheLine(record *run.Object) error {
	reviewed := record.Str("head_sha")
	head, err := p.git().Must("rev-parse", "HEAD")
	if err != nil || !record.Truthy("landing_fix") || head == reviewed {
		return err
	}
	_, err = p.git().Must("reset", "--hard", reviewed)
	return err
}
