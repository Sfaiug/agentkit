//go:build linux

package loop

import (
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"agentkit/internal/run"
)

// A suite's red at a seat's own PR's landing is its writer's, Python's fail_pr_landing: each of
// conflictRounds reds leaves the line for a fixer turn of its own, and the next one fails the run,
// saying how many.
func TestAnOwnPRsSuiteRedIsItsWritersUpToTheBound(t *testing.T) {
	l, p, _ := pullRig(t, "open")
	log := filepath.Join(l.dir, "lander.log")
	if err := os.WriteFile(log, []byte("FAILED test_contrib\n"), 0o666); err != nil {
		t.Fatal(err)
	}
	fix := run.Fields("line", "FAILED test_contrib", "log", log, "command", "pytest", "piece", "")
	for red := 1; red <= conflictRounds+1; red++ {
		// the run woken in its line on the red, its last fix re-reviewed
		if err := run.Change(l.dir, func(record *run.Object) error {
			run.SetAll(record, "own_pr", true, "state", "waiting", "review", run.Fields("verdict", "PASS"),
				"waiting_on", run.Fields("line", ".merge-acme.lock", "joined", 1, "fix", fix))
			record.Delete("own_pr_wait")
			return nil
		}); err != nil {
			t.Fatal(err)
		}
		if err := (&ownPull{p}).failLanding(l, recorded(t, l), fix); err != nil {
			t.Fatal(err)
		}
		record := recorded(t, l)
		_, turn := ownFix(record)
		switch {
		case record.Has("waiting_on") || record.Str("verdict") != "FAIL" || record.Dict("final_check").Str("where") != "landing":
			t.Fatalf("red %d did not fail the landing: %s", red, run.Line(record))
		case red <= conflictRounds && (record.Str("state") != "running" || record.Str("own_pr_wait") != p.sha ||
			turn != fmt.Sprintf("landing-%d-fixer", red)):
			t.Fatalf("red %d owes no fixer of its own: %s", red, run.Line(record))
		case red > conflictRounds && (record.Str("state") != "fail" || record.Has("landing_reds") || record.Truthy("landing_fix") ||
			record.Str("merge_note") != "landing failed 4 times: FAILED test_contrib"):
			t.Fatalf("the red past the bound did not fail the run: %s", run.Line(record))
		}
	}
	if text, err := os.ReadFile(filepath.Join(l.dir, "landing-findings.md")); err != nil || !strings.Contains(string(text), "\n\n## Landing failed\nFAILED test_contrib\n") {
		t.Fatalf("the findings hold no landing failure: %v\n%s", err, text)
	}
}
