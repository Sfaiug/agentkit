package handback

import (
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"

	"agentkit/internal/run"
	"agentkit/internal/task"
)

func followupRig(t *testing.T, workers string) (string, string) {
	t.Helper()
	home := t.TempDir()
	t.Setenv("HOME", home)
	t.Setenv("USERPROFILE", home)
	state := filepath.Join(home, ".agentkit", "state")
	dir := filepath.Join(run.Runs(), "parent")
	for _, path := range []string{state, dir} {
		if err := os.MkdirAll(path, 0o700); err != nil {
			t.Fatal(err)
		}
	}
	os.WriteFile(filepath.Join(state, "session-acme.json"), []byte(`{"workers": `+workers+`}`), 0o600)
	repo := filepath.Join(home, "widgets")
	git := func(args ...string) string {
		t.Helper()
		cmd := exec.Command("git", args...)
		cmd.Env = append(os.Environ(), "GIT_AUTHOR_NAME=acme", "GIT_AUTHOR_EMAIL=acme@example.com",
			"GIT_COMMITTER_NAME=acme", "GIT_COMMITTER_EMAIL=acme@example.com")
		out, err := cmd.CombinedOutput()
		if err != nil {
			t.Fatalf("git %v: %s: %v", args, out, err)
		}
		return strings.TrimSpace(string(out))
	}
	git("init", "-q", "-b", "main", repo)
	git("-C", repo, "commit", "-q", "--allow-empty", "-m", "init")
	sha := git("-C", repo, "rev-parse", "HEAD")
	if err := run.Create(dir, run.Fields("run_id", "parent", "state", "pass", "merged", true,
		"launched_session", "acme", "repo", repo, "base", "main", "base_sha", sha,
		"followups", []any{"retry.txt:1 - fragile retry"},
		"followup_checks", run.Fields("retry.txt:1 - fragile retry", "test -f sturdy.txt"),
		"followup_commits", run.Fields("retry.txt:1 - fragile retry", sha))); err != nil {
		t.Fatal(err)
	}
	return dir, filepath.Join(state, "plan-acme.md")
}

func TestAHandoffRecoversItsQueuedFixAndDoesNotStartItTwice(t *testing.T) {
	dir, plan := followupRig(t, `["opus"]`)
	prepared, started := 0, 0
	prepare := func(child string, state, origin *run.Object) (func() error, error) {
		prepared++
		run.SetAll(origin, "run_id", filepath.Base(child), "state", "queued", "slot_waiting", true,
			"launched_session", "acme")
		if err := run.Create(child, origin); err != nil {
			t.Fatal(err)
		}
		return func() error {
			started++
			text, err := os.ReadFile(plan)
			if err != nil || !strings.Contains(string(text), " · deferred · written ") {
				t.Fatalf("the fix started before its line: %q: %v", text, err)
			}
			return nil
		}, nil
	}
	for attempt := 0; attempt < 3; attempt++ {
		if err := StartFollowups(dir, prepare, func(line string) { t.Log(line) }); err != nil {
			t.Fatal(err)
		}
		if prepared != 1 || started != 1 {
			t.Fatalf("prepared %d, started %d", prepared, started)
		}
		if attempt == 1 { // a cut-off before the parent recorded its completed handoff
			run.Change(dir, func(record *run.Object) error { record.Delete("followup_runs"); return nil })
		}
	}
	text, _ := os.ReadFile(plan)
	if strings.Count(string(text), "- [ ] ") != 1 {
		t.Fatalf("duplicate plan lines: %s", text)
	}
	state, _ := run.Read(dir)
	if len(state.List("followup_runs")) != 1 || len(state.List("followup_plan")) != 1 {
		t.Fatal(run.Line(state))
	}
	// Recovery must also keep a line whose fix delivered before the handoff was retried.
	child := filepath.Join(run.Runs(), run.Text(state.List("followup_runs")[0]))
	run.Change(child, func(record *run.Object) error { run.SetAll(record, "state", "pass", "merged", true); return nil })
	done := strings.TrimSpace(strings.Replace(string(text), "- [ ] ", "- [x] ", 1)) + " · done " + state.Str("base_sha")[:12] + " fix\n"
	os.WriteFile(plan, []byte(done), 0o600)
	run.Change(dir, func(record *run.Object) error { record.Delete("followup_runs"); return nil })
	if err := StartFollowups(dir, prepare, func(line string) { t.Log(line) }); err != nil {
		t.Fatal(err)
	}
	text, _ = os.ReadFile(plan)
	if string(text) != done || prepared != 1 {
		t.Fatalf("recovery repeated delivered work: %s", text)
	}
}

func TestANoExecutorSeatPlansItsOwnWorkAndAClosedSeatStartsNothing(t *testing.T) {
	for _, closed := range []bool{false, true} {
		t.Run(map[bool]string{false: "no executor", true: "closed"}[closed], func(t *testing.T) {
			dir, plan := followupRig(t, `[]`)
			if closed {
				os.WriteFile(filepath.Join(filepath.Dir(plan), "seat-acme.json"), []byte(`{"stopped_at": 1}`), 0o600)
			}
			err := StartFollowups(dir, func(string, *run.Object, *run.Object) (func() error, error) {
				t.Fatal("nothing should launch")
				return nil, nil
			}, func(line string) { t.Log(line) })
			if err != nil {
				t.Fatal(err)
			}
			text, err := os.ReadFile(plan)
			if closed && !os.IsNotExist(err) || !closed && (err != nil || strings.Contains(string(text), " · deferred")) {
				t.Fatalf("plan %q: %v", text, err)
			}
		})
	}
}

func TestAFollowupCommandIsNormalizedForItsPlanAndFixReceipt(t *testing.T) {
	const check = "test -f sturdy.txt"
	for _, workers := range []string{`[]`, `["opus"]`} {
		t.Run(workers, func(t *testing.T) {
			dir, plan := followupRig(t, workers)
			run.Change(dir, func(record *run.Object) error {
				record.Dict("followup_checks").Set("retry.txt:1 - fragile retry", "\x1f \t"+check+"\r\n")
				return nil
			})
			prepared := false
			err := StartFollowups(dir, func(child string, state, origin *run.Object) (func() error, error) {
				prepared = true
				if got := origin.Dict("followup").Str("check"); got != check {
					t.Errorf("fix receipt check = %q, want %q", got, check)
				}
				_, commands, err := task.Read(filepath.Join(child, "task.md"))
				if err != nil || len(commands) != 1 || commands[0] != check {
					t.Errorf("fix commands = %q: %v", commands, err)
				}
				return func() error { return nil }, nil
			}, func(line string) { t.Log(line) })
			if err != nil || prepared != (workers != `[]`) {
				t.Fatalf("prepared = %v: %v", prepared, err)
			}
			text, err := os.ReadFile(plan)
			if err != nil || strings.Count(string(text), "\n") != 1 || !strings.Contains(string(text), " · check: `"+check+"` · ") {
				t.Fatalf("unreadable check line: %q: %v", text, err)
			}
		})
	}
}
