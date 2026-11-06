package run

import (
	"os"
	"path/filepath"
	"testing"

	"agentkit/internal/config"
)

func TestARunHoldsToTheNumbersItsRecordKeptUnderEitherName(t *testing.T) {
	home := t.TempDir()
	t.Setenv("HOME", home)
	t.Setenv("USERPROFILE", home)
	if err := os.MkdirAll(filepath.Join(home, ".agentkit"), 0o777); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(home, ".agentkit", "config.toml"), []byte("review_rounds=4\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	said := config.Numbers{Rounds: 1, ReviewLines: config.NoLimit, SeatLines: config.AtMost(0)}
	for _, example := range []struct {
		record *Object
		want   config.Numbers
	}{
		{Fields("policy", Fields(said.Said()...)), said},
		// an old run's, as Python's rename_policy reads it: its new name kept where it holds both
		{Fields("policy", Fields("rounds", 2, "review_lines", 120, "seat_lines", 10)), config.Numbers{Rounds: 2, ReviewLines: config.AtMost(120), SeatLines: config.AtMost(10)}},
		{Fields("policy", Fields("rounds", 2, "review_rounds", 1)), config.Numbers{Rounds: 1, ReviewLines: config.AtMost(300), SeatLines: config.AtMost(50)}},
		{Fields(), config.Numbers{Rounds: 4, ReviewLines: config.AtMost(300), SeatLines: config.AtMost(50)}},
	} {
		if numbers, err := Policy(example.record); err != nil || numbers != example.want {
			t.Errorf("%s: %v %v, want %v", Line(example.record), numbers, err, example.want)
		}
	}
	if got := Line(Fields(said.Said()...)); got != `{"review_rounds": 1, "executor_lines": "no limit", "orchestrator_lines": 0}` {
		t.Errorf("recorded as %s", got)
	}
}
