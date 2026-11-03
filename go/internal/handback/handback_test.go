package handback

import (
	"path/filepath"
	"strings"
	"testing"

	"agentkit/internal/run"
)

func blocked(why string) *run.Object {
	return run.Fields("state", "blocked", "error", why, "rounds", run.Number("3"), "round_summaries", []any{},
		"branch", "ak/add-retry-file")
}

func TestABlockedEndingIsToldInItsDecisionLineWhole(t *testing.T) {
	home := t.TempDir()
	t.Setenv("HOME", home)
	dir := filepath.Join(home, ".agentkit", "runs", "20261103-0931-add-retry-file")
	got := decisionLine(blocked("cannot be\n  done as written"), dir)
	want := "run 20261103-0931-add-retry-file BLOCKED (0 of 3): cannot be done as written. Next: rewrite the task " +
		"and relaunch it with `from: ak/add-retry-file`. Result: ~/.agentkit/runs/20261103-0931-add-retry-file/result.md"
	if got != want {
		t.Fatalf("got  %q\nwant %q", got, want)
	}
}

func TestALineGoWouldCutOrDoesNotBuildIsTheTicks(t *testing.T) {
	dir := filepath.Join(t.TempDir(), "20261103-0931-add-retry-file")
	if got := decisionLine(blocked(strings.Repeat("word ", 80)), dir); got != "" {
		t.Fatalf("a reason Python cuts to its sentences was said whole: %q", got)
	}
	failed := blocked("why")
	failed.Set("state", "fail")
	if got := decisionLine(failed, dir); got != "" {
		t.Fatalf("a FAIL got a line: %q", got)
	}
}

func TestOnlyThisAttemptsMarkSaysItWasHandedBack(t *testing.T) {
	for _, each := range []struct {
		record *run.Object
		told   bool
	}{
		{run.Fields("handed_back", run.Float(90), "finished_at", run.Float(100)), false},
		{run.Fields("handed_back", run.Float(100), "finished_at", run.Float(100)), true},
		{run.Fields("handed_back", true, "finished_at", run.Float(100)), true},
		{run.Fields("handed_back", false), false},
		{run.Fields("handed_back", run.Float(90), "finished_at", nil, "interrupted_at", run.Float(80)), true},
	} {
		if got := handedBack(each.record); got != each.told {
			t.Errorf("%s: got %v", run.Line(each.record), got)
		}
	}
}

func TestAnEndingOverAnHourOldIsHistory(t *testing.T) {
	now := seconds()
	for _, each := range []struct {
		record *run.Object
		old    bool
	}{
		{run.Fields("finished_at", run.Float(now-2*maxAge)), true},
		{run.Fields("finished_at", run.Float(now-60)), false},
		{run.Fields("finished_at", nil, "started_at", run.Float(now-2*maxAge)), true},
		{run.Fields("finished_at", nil), false},
	} {
		if got := history(each.record); got != each.old {
			t.Errorf("%s: got %v", run.Line(each.record), got)
		}
	}
}
