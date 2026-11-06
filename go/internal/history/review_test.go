package history

import (
	"testing"

	"agentkit/internal/config"
	"agentkit/internal/run"
)

// A finished review is kept once, by its output directory, and only for a run with a row: its
// records with a proof each a findings row, recorded again or not.
func TestAReviewIsKeptOnceAndOnlyForARunWithARow(t *testing.T) {
	home(t)
	log, lines := said()
	reviewer := config.Model{Harness: "codex", ID: "astra", Efforts: map[string]string{"effort": "high"}}
	records := []*run.Object{
		record(t, `{"kind": "finding", "path": "api.py", "line": 3, "evidence": {"run": "false", "commit": "abc", "returncode": 1, "base": {"sha": "def", "returncode": 0}}}`),
		record(t, `{"kind": "done"}`),
	}
	unknown := record(t, `{"run_id": "20261105-1300-fix-ui"}`)
	Reviewed(unknown, "/runs/fix-ui/round-1/reviewer", reviewer, 1, "FAIL", records, log)
	ran := record(t, `{"run_id": "20261105-1200-fix-api", "state": "queued"}`)
	Start(ran, log)
	for range 2 {
		Reviewed(ran, "/runs/fix-api/round-1/reviewer", reviewer, 1, "FAIL", records, log)
	}
	db, err := Open()
	if err != nil {
		t.Fatal(err)
	}
	defer db.Close()
	reviews := query(t, db, "SELECT run_id, blocking, effort FROM reviews")
	findings := query(t, db, "SELECT run_id, kind, proof, commit_exit, base_exit FROM findings")
	if len(*lines) != 0 || len(reviews) != 1 || reviews[0]["run_id"] != "20261105-1200-fix-api" || len(findings) != 1 ||
		findings[0]["proof"] != "false" || findings[0]["commit_exit"] != int64(1) || findings[0]["base_exit"] != int64(0) {
		t.Fatalf("said %q, kept %v and %v", *lines, reviews, findings)
	}
}
