package launch

import (
	"errors"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"agentkit/internal/run"
)

func TestOnlyAFailAtItsBudgetTakesMoreRoundsAndOnlyMore(t *testing.T) {
	home := t.TempDir()
	t.Setenv("HOME", home)
	t.Setenv("USERPROFILE", home)
	dir := filepath.Join(run.Runs(), "fix-api")
	if err := os.MkdirAll(dir, 0o700); err != nil {
		t.Fatal(err)
	}
	policy, err := run.PolicyRounds(run.Fields())
	if err != nil || policy < 2 {
		t.Fatalf("the host's rounds: %d, %v", policy, err)
	}
	failed := func(state string) *run.Object {
		return run.Fields("run_id", "fix-api", "state", state, "worktree", t.TempDir(), "rounds", 1,
			"round_summaries", []any{run.Fields()}, "review_pending", run.Fields("round", 1), "merge_note", "not merged")
	}
	if _, _, err := raise(dir, failed("interrupted"), 2); !errors.Is(err, ErrPython) {
		t.Fatalf("a run not at its budget: %v", err)
	}
	if _, why, _ := raise(dir, failed("fail"), 1); !strings.Contains(why, "give --rounds N above it, at most") {
		t.Fatalf("no more rounds: %q", why)
	}
	if _, why, _ := raise(dir, failed("fail"), policy+1); !strings.Contains(why, "over this change's budget") {
		t.Fatalf("past the change's budget: %q", why)
	}
	order, why, err := raise(dir, failed("fail"), 2)
	if order == nil || why != "" || err != nil {
		t.Fatalf("refused: %q, %v", why, err)
	}
	record := failed("fail")
	order(record)
	if rounds, _ := record.Int("rounds"); rounds != 2 || record.Has("review_pending") || record.Truthy("merge_note") || run.AtBudget(record) {
		t.Fatalf("not raised: %s", run.Line(record))
	}
}
