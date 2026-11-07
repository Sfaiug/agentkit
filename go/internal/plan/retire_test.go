//go:build unix

// A test of its own package, so the stop it measures is Go's own: loop gives it to plan.
package plan_test

import (
	"context"
	"errors"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"

	"agentkit/internal/history"
	_ "agentkit/internal/loop"
	"agentkit/internal/plan"
	"agentkit/internal/run"
)

// Two repeats of one line are ticked, and a history.db, which makes a stop Python's, appears in
// the home once the first stop is decided, as it is written: both runs end stopped and the line
// ticks.  Where the home held one before the decision, the command hands over, both runs left
// queued and the plan as it was.
func TestATickDecidesEveryStopBeforeWritingOne(t *testing.T) {
	for _, before := range []bool{false, true} {
		home := t.TempDir()
		t.Setenv("HOME", home)
		t.Setenv("USERPROFILE", home)
		t.Setenv("XDG_RUNTIME_DIR", home) // no user manager, whose units Python stops
		t.Setenv("GIT_CONFIG_NOSYSTEM", "1")
		for _, key := range []string{"GIT_AUTHOR_NAME", "GIT_AUTHOR_EMAIL", "GIT_COMMITTER_NAME", "GIT_COMMITTER_EMAIL"} {
			t.Setenv(key, "acme")
		}
		shell(t, home, "git init -q --bare -b main origin.git && git init -q -b main acme && cd acme && "+
			"git commit -q --allow-empty -m init && git remote add origin ../origin.git && git push -q origin main")
		repo, _ := filepath.EvalSymlinks(filepath.Join(home, "acme"))
		state := filepath.Join(home, ".agentkit", "state")
		if os.MkdirAll(state, 0o700) != nil || os.WriteFile(filepath.Join(state, "session-fix-api.json"), []byte(`{}`), 0o600) != nil {
			t.Fatal("no seat")
		}
		ctx := context.Background()
		if _, err := plan.Add(ctx, "fix-api", repo, "Fix the mode", "test -f feature.txt"); err != nil {
			t.Fatal(err)
		}
		repeats := []string{filepath.Join(run.Runs(), "one"), filepath.Join(run.Runs(), "two")}
		for _, dir := range repeats {
			record := `{"run_id": "` + filepath.Base(dir) + `", "launched_session": "fix-api", "repo": "` + repo + `", ` +
				`"state": "queued", "slot_waiting": true, "pid": null, "followup": {"check": "test -f feature.txt"}}`
			if os.MkdirAll(dir, 0o700) != nil || os.WriteFile(filepath.Join(dir, "run.json"), []byte(record), 0o600) != nil {
				t.Fatal("no run")
			}
		}
		shell(t, repo, "echo fixed > feature.txt && git add -A && git commit -q -m 'land the feature' && git push -q origin main")
		planned := filepath.Join(state, "plan-fix-api.md")
		was, _ := os.ReadFile(planned)
		appear := func() {
			if os.WriteFile(history.Path(), []byte("no database\n"), 0o600) != nil {
				t.Fatal("no history.db")
			}
		}
		if before {
			appear()
		}
		decide := plan.Ending
		plan.Ending = func(dir string, record *run.Object) func(string) {
			stop := decide(dir, record)
			if stop == nil {
				return nil
			}
			return func(why string) {
				if _, err := os.Stat(history.Path()); err != nil {
					appear()
				}
				stop(why)
			}
		}
		_, err := plan.List(ctx, "fix-api")
		plan.Ending = decide
		now, _ := os.ReadFile(planned)
		for _, dir := range repeats {
			record, _ := run.Read(dir)
			if before && (!errors.Is(err, plan.ErrUnread) || record.Str("state") != "queued" || string(now) != string(was)) {
				t.Fatalf("held before: %v, %s, plan %q", err, run.Line(record), now)
			}
			if !before && (err != nil || record.Str("state") != "stopped" || !strings.Contains(record.Str("error"), `plan line "Fix the mode" ticked on `) ||
				!strings.HasPrefix(string(now), "- [x] Fix the mode")) {
				t.Fatalf("appeared once decided: %v, %s, plan %q", err, run.Line(record), now)
			}
		}
	}
}

func shell(t *testing.T, dir, script string) {
	t.Helper()
	command := exec.Command("bash", "-c", script)
	command.Dir = dir
	if said, err := command.CombinedOutput(); err != nil {
		t.Fatalf("%s: %v: %s", script, err, said)
	}
}
