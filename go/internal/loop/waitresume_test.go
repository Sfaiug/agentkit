//go:build linux

package loop

import (
	"errors"
	"os"
	"path/filepath"
	"testing"

	"agentkit/internal/run"
)

func TestWaitingResumeRestoresOnlyTheReviewOfItsCheckoutAndSpendsNoTaskRound(t *testing.T) {
	for _, changed := range []bool{false, true} {
		t.Run(run.Text(changed), func(t *testing.T) {
			l, r := repoRig(t)
			settings := "[models.opus]\nharness='claude'\nmodel='opus'\neffort='high'\nprovider='anthropic'\n[models.astra]\nharness='codex'\nmodel='astra'\neffort='high'\nprovider='openai'\n[providers.anthropic]\nmode='subscription'\n[providers.openai]\nmode='subscription'\n"
			if err := os.WriteFile(filepath.Join(os.Getenv("HOME"), ".agentkit", "config.toml"), []byte(settings), 0o600); err != nil {
				t.Fatal(err)
			}
			head, tree, err := r.identity()
			if err != nil {
				t.Fatal(err)
			}
			review := run.Fields("executor", "opus", "reviewer", "astra", "executor_provider", "anthropic", "reviewer_provider", "openai",
				"verdict", "PASS", "done_when", true, "returncode", 0, "head_sha", head, "tree_sha", tree)
			if err := run.Change(l.dir, func(record *run.Object) error {
				run.SetAll(record, "state", "waiting", "launched_session", "acme", "waiting_on", run.Fields("ref", "origin/main", "sha", head),
					"base", "main", "target", "main", "base_sha", r.baseSHA, "rounds", 3, "round_summaries", []any{review.Copy()},
					"review", review, "verdict", "FAIL", "merge_note", "the rebase of origin/main conflicted", "merge_failed", true,
					"executor", "opus", "reviewer", "astra", "handback_pending", true)
				return nil
			}); err != nil {
				t.Fatal(err)
			}
			if err := os.WriteFile(filepath.Join(l.dir, "log.txt"), []byte("WARN not merged: conflict\n"), 0o600); err != nil {
				t.Fatal(err)
			}
			if changed {
				shell(t, r.wt, "echo other > other.txt && git add -A && git commit -qm other")
			}
			before, _ := run.Read(l.dir)
			err = Reopen(l.dir, before, nil)
			if changed {
				after, _ := run.Read(l.dir)
				if !errors.Is(err, ErrChanged) || !run.Equal(after, before) {
					t.Fatalf("resumed unreviewed work: %v", err)
				}
				return
			}
			after, _ := run.Read(l.dir)
			if err != nil || after.Str("verdict") != "PASS" || after.Has("waiting_on") || after.Truthy("merge_failed") || after.Truthy("handback_pending") {
				t.Fatalf("resume: %v: %s", err, run.Line(after))
			}
			l.prior = true
			l.takeUp(after)
			if passed, err := l.rounds(); err != nil || !passed || l.rnd != 1 {
				t.Fatalf("saved review spent another task round: %v, %v, %d", passed, err, l.rnd)
			}
		})
	}
}
