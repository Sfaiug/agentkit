//go:build linux

package loop

import (
	"context"
	"os"
	"path/filepath"
	"testing"
	"time"

	"agentkit/internal/history"
	"agentkit/internal/run"
)

// The loop keeps its run's history row as Python's does: what a save moves of the row's workers
// and efforts is there at once, and its ending closes the row.
func TestTheLoopKeepsItsRunsRow(t *testing.T) {
	l := rig(t, time.Minute)
	launched, _ := run.Read(l.dir)
	history.Start(launched, nil)
	if err := l.save(func(record *run.Object) {
		run.SetAll(record, "executor", "opus", "reviewer", "astra", "executor_effort", "high")
	}); err != nil {
		t.Fatal(err)
	}
	if code := End(l.dir, "acme"); code != 2 {
		t.Fatalf("exit %d", code)
	}
	db, err := history.Open()
	if err != nil || db == nil {
		t.Fatalf("got (%v, %v)", db, err)
	}
	defer db.Close()
	rows, _ := db.EndedRuns(0, float64(time.Now().Unix()+60))
	if len(rows) != 1 || rows[0].Text("final_state") != "error" || rows[0].Text("executor") != "opus" ||
		rows[0].Text("executor_effort") != "high" {
		t.Fatalf("rows %v", rows)
	}
}

// A seat's follow-up has its row from its receipt on, as Python's capture_launch writes it, and
// one whose workplace cannot be cut ends that row carrying its task's size, which Python's
// history_start writes before any checkout.
func TestAFollowUpCutOffBeforeItsWorkplaceKeepsItsRow(t *testing.T) {
	_, repo := repoRig(t)
	seatLaunchFixture(t)
	child := filepath.Join(run.Runs(), "fix")
	os.Mkdir(child, 0o700)
	t.Setenv("AGENTKIT_RUN", child)
	text := "---\nrepo: " + repo.repo + "\nbase: main\n---\n# Fix retry\n\n## Goal\nFix retry.\n\n## Done when\n```bash\ntrue\n```\n"
	os.WriteFile(filepath.Join(child, "task.md"), []byte(text), 0o600)
	if _, err := launchForSeat(child, run.Fields("launched_session", "acme"), run.Fields("repo", repo.repo, "followup", run.Fields("check", "false"))); err != nil {
		t.Fatal(err)
	}
	if run.Historyless() {
		t.Fatal("the receipt made no history.db")
	}
	// its repository has no origin to fetch
	l := &loop{ctx: context.Background(), dir: child, id: "fix"}
	if code := l.finish(l.work()); code != 1 {
		t.Fatalf("exit %d", code)
	}
	db, err := history.Open()
	if err != nil || db == nil {
		t.Fatalf("got (%v, %v)", db, err)
	}
	defer db.Close()
	rows, _ := db.EndedRuns(0, float64(time.Now().Unix()+60))
	if len(rows) != 1 || rows[0].Text("final_state") != "exhausted" || rows[0].Text("kind") != "follow-up" ||
		rows[0]["task_words"] == nil || rows[0]["task_points"] == nil || rows[0]["task_checks"] != int64(1) {
		t.Fatalf("rows %v", rows)
	}
}
