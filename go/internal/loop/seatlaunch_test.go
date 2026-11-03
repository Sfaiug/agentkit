//go:build linux

package loop

import (
	"os"
	"path/filepath"
	"strings"
	"testing"

	"agentkit/internal/run"
)

func TestAFixWaitsFromItsFirstReceiptWithTheSeatsCurrentListsAndNoParent(t *testing.T) {
	l := rig(t, 0)
	home := filepath.Join(os.Getenv("HOME"), ".agentkit")
	os.MkdirAll(filepath.Join(home, "state"), 0o700)
	settings, err := os.ReadFile("../../../config.default.toml")
	if err != nil {
		t.Fatal(err)
	}
	os.WriteFile(filepath.Join(home, "config.toml"), settings, 0o600)
	os.WriteFile(filepath.Join(home, "state", "session-acme.json"),
		[]byte(`{"workers": ["opus"], "reviewers": ["astra"], "efforts": {"opus": {"effort": "high"}}}`), 0o600)
	t.Setenv("AK_RUN_DEPTH", "3")
	t.Setenv("AK_PARENT_RUN", "parent")
	t.Setenv("AK_RUN_ROLE", "executor")
	t.Setenv("AGENTKIT_JOB_DIR", "/old-job")
	child := filepath.Join(run.Runs(), "fix")
	os.Mkdir(child, 0o700)
	os.WriteFile(filepath.Join(child, "task.md"), []byte("# Fix retry\n"), 0o600)
	parent := run.Fields("launched_session", "acme", "workers", []any{"astra"}, "reviewers", []any{"opus"})
	start, err := launchForSeat(child, parent, run.Fields("followup", run.Fields("check", "false"), "repo", os.Getenv("HOME")))
	if err != nil || start == nil {
		t.Fatalf("prepare: %v", err)
	}
	record, _ := run.Read(child)
	if record.Str("state") != "queued" || !record.Truthy("slot_waiting") || record.Truthy("slot_started_at") ||
		record.Truthy("run_depth") || record.Get("parent_run") != nil || run.Seat(record) != "acme" ||
		run.Text(record.List("workers")[0]) != "opus" || run.Text(record.List("reviewers")[0]) != "astra" ||
		record.Dict("efforts").Dict("opus").Str("effort") != "high" {
		t.Fatal(run.Line(record))
	}
	env, err := siblingEnv(record)
	if err != nil {
		t.Fatal(err)
	}
	for _, pair := range env {
		key, value, _ := strings.Cut(pair, "=")
		switch key {
		case "AGENTKIT_RUN", "AK_PARENT_RUN", "AK_RUN_ROLE", "AGENTKIT_JOB_DIR":
			t.Fatalf("inherited the ending's %s", key)
		case "AK_RUN_DEPTH":
			if value != "0" {
				t.Fatal(pair)
			}
		}
	}
	failedStart(child, "cannot spawn")
	record, _ = run.Read(child)
	if record.Str("state") != "queued" || !record.Truthy("slot_waiting") || record.Get("pid") != nil {
		t.Fatalf("a failed launch lost its queue place: %s", run.Line(record))
	}
	run.Change(child, func(record *run.Object) error { record.Set("pid", os.Getpid()); return nil })
	l.dir = child
	if err := l.admitQueued(); err != nil {
		t.Fatal(err)
	}
	record, _ = run.Read(child)
	if record.Str("state") != "running" || record.Truthy("slot_waiting") || !record.Truthy("slot_started_at") {
		t.Fatalf("never claimed its own slot: %s", run.Line(record))
	}
}

func TestASeatsRunWokenByTheSharedLineCanLand(t *testing.T) {
	l := rig(t, 0)
	record := run.Fields("state", "waiting", "launched_session", "acme", "scope", "none",
		"waiting_on", run.Fields("line", ".merge-acme.lock", "land", "tree"),
		"repo", l.workspace, "worktree", l.workspace, "branch", "ak/fix", "base", "main", "base_sha", "abc1234")
	if !Woken(record) {
		t.Fatal("a seat's delivery was left to Python")
	}
}
