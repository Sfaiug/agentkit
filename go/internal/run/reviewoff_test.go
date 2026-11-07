package run

import (
	"os"
	"path/filepath"
	"testing"
	"time"
)

func TestAReviewOffRunSpendsNoRoundOfItsChange(t *testing.T) {
	home := t.TempDir()
	t.Setenv("HOME", home)
	t.Setenv("USERPROFILE", home)
	failed := Fields("run_id", "fix-api", "state", "fail", "rounds", 2, "policy", Fields("review_rounds", 3),
		"round_summaries", []any{Fields(), Fields()})
	// in its first turn, which would be a round under way were review on
	unreviewed := Fields("run_id", "fix-api-checks", "change", "fix-api", "state", "running", "step_round", 1,
		"policy", Fields("review_rounds", 0))
	for id, record := range map[string]*Object{"fix-api": failed, "fix-api-checks": unreviewed} {
		if err := os.MkdirAll(filepath.Join(Runs(), id), 0o700); err != nil {
			t.Fatal(err)
		}
		if err := Create(filepath.Join(Runs(), id), record); err != nil {
			t.Fatal(err)
		}
	}
	dir := filepath.Join(Runs(), "fix-api")
	for own, want := range map[int]int{0: 3, 2: 1} {
		if left, why, err := ChangeLeft(failed, dir, 3, own, time.Now()); left != want || why != "" || err != nil {
			t.Fatalf("with %d of its own spent: (%d, %q, %v), want %d left", own, left, why, err, want)
		}
	}
}
