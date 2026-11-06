//go:build linux

package loop

import (
	"context"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"agentkit/internal/config"
	"agentkit/internal/lock"
	"agentkit/internal/run"
)

func seatLaunchFixture(t *testing.T) {
	t.Helper()
	previous := HoldSlots
	HoldSlots = func(ctx context.Context) (*os.File, error) {
		return lock.Wait(ctx, filepath.Join(run.Runs(), ".slots.lock"))
	}
	t.Cleanup(func() { HoldSlots = previous })
	home := filepath.Join(os.Getenv("HOME"), ".agentkit")
	os.MkdirAll(filepath.Join(home, "state"), 0o700)
	settings, err := os.ReadFile("../../../config.default.toml")
	if err != nil {
		t.Fatal(err)
	}
	os.WriteFile(filepath.Join(home, "config.toml"), settings, 0o600)
	os.WriteFile(filepath.Join(home, "state", "session-acme.json"),
		[]byte(`{"workers": ["opus"], "reviewers": ["astra"], "efforts": {"opus": {"effort": "high"}}}`), 0o600)
}

func TestAFixWaitsFromItsFirstReceiptWithTheSeatsCurrentListsAndNoParent(t *testing.T) {
	l := rig(t, 0)
	seatLaunchFixture(t)
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

func TestAFixCapturesTheCurrentDefaultBranchPolicy(t *testing.T) {
	_, repo := repoRig(t)
	seatLaunchFixture(t)
	agents := filepath.Join(repo.repo, "AGENTS.md")
	os.WriteFile(agents, []byte("---\nreview_rounds: 1\nexecutor_lines: 60\norchestrator_lines: 0\n---\n"), 0o600)
	shell(t, repo.repo, "git add AGENTS.md && git commit -qm policy && git update-ref refs/remotes/origin/main HEAD && git symbolic-ref refs/remotes/origin/HEAD refs/remotes/origin/main")
	// Neither the parent's older policy nor the checkout's uncommitted edits set this launch's limits.
	os.WriteFile(agents, []byte("---\nreview_rounds: 2\nexecutor_lines: 90\norchestrator_lines: 50\n---\n"), 0o600)
	child := filepath.Join(run.Runs(), "fix")
	os.Mkdir(child, 0o700)
	path := filepath.Join(child, "task.md")
	os.WriteFile(path, []byte("# Fix retry\n"), 0o600)
	parent := run.Fields("launched_session", "acme", "policy", run.Fields("rounds", 3, "review_lines", 300, "seat_lines", 50))
	_, err := launchForSeat(child, parent, run.Fields("repo", repo.repo, "followup", run.Fields("check", "false")))
	if err != nil {
		t.Fatal(err)
	}
	record, err := run.Read(child)
	if err != nil {
		t.Fatal(err)
	}
	rounds, _, err := budget(nil, path, child)
	if err != nil || rounds != 1 || numbersOf(record) != config.AtMost(60) || record.Dict("policy") == nil || record.Dict("policy").Get("orchestrator_lines") != run.Number("0") {
		t.Fatalf("fix policy = %s, budget = %d: %v", run.Line(record.Get("policy")), rounds, err)
	}
}

// A fix whose project turned review off or a line limit to none since is Python's: Go writes no
// receipt for it.
func TestAFixGoDoesNotCarryGetsNoReceipt(t *testing.T) {
	_, repo := repoRig(t)
	seatLaunchFixture(t)
	for _, front := range []string{"review_rounds: 0", "executor_lines: no limit", "orchestrator_lines: no limit"} {
		os.WriteFile(filepath.Join(repo.repo, "AGENTS.md"), []byte("---\n"+front+"\n---\n"), 0o600)
		shell(t, repo.repo, "git add AGENTS.md && git commit -qm policy && git update-ref refs/remotes/origin/main HEAD && git symbolic-ref refs/remotes/origin/HEAD refs/remotes/origin/main")
		child := filepath.Join(run.Runs(), "fix")
		os.MkdirAll(child, 0o700)
		os.WriteFile(filepath.Join(child, "task.md"), []byte("# Fix retry\n"), 0o600)
		start, err := launchForSeat(child, run.Fields("launched_session", "acme"), run.Fields("repo", repo.repo))
		if _, stat := os.Stat(filepath.Join(child, "run.json")); err == nil || start != nil || !os.IsNotExist(stat) {
			t.Fatalf("%s: launched %v, %v", front, start != nil, err)
		}
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
