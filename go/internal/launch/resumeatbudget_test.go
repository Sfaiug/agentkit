package launch

import (
	"fmt"
	"io"
	"os"
	"path/filepath"
	"testing"

	"agentkit/internal/box"
	"agentkit/internal/run"
)

func TestAFailAtItsBudgetResumedWithNoRoundsIsRefusedWithTheMostItMayAsk(t *testing.T) {
	if err := box.Check(); err != nil {
		t.Skip(err) // Python's refusal, before the budget's
	}
	home := t.TempDir()
	for key, value := range map[string]string{"HOME": home, "USERPROFILE": home, "AGENTKIT_SESSION": "", "AGENTKIT_RUN_DIR": ""} {
		t.Setenv(key, value)
	}
	dir := filepath.Join(run.Runs(), "fix-api")
	if err := os.MkdirAll(dir, 0o700); err != nil {
		t.Fatal(err)
	}
	if err := run.Create(dir, run.Fields("run_id", "fix-api", "state", "fail", "worktree", t.TempDir(), "rounds", 1,
		"round_summaries", []any{run.Fields()})); err != nil {
		t.Fatal(err)
	}
	policy, err := run.PolicyRounds(run.Fields())
	if err != nil {
		t.Fatal(err)
	}
	before, _ := os.ReadFile(filepath.Join(dir, "run.json"))
	code, why, err := Resume("fix-api", 0, false, io.Discard, io.Discard)
	after, _ := os.ReadFile(filepath.Join(dir, "run.json"))
	want := fmt.Sprintf("fix-api FAILed at its round budget (1); give --rounds N above it, at most %d, to continue", policy)
	if code != 2 || why != want || err != nil || string(after) != string(before) {
		t.Fatalf("got (%d, %q, %v), want (2, %q); run.json %s", code, why, err, want, after)
	}
}
