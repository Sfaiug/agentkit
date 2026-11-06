package launch

import (
	"errors"
	"os"
	"path/filepath"
	"testing"

	"agentkit/internal/loop"
	"agentkit/internal/run"
)

func TestAResumeDecisionCannotAdoptALaterAttempt(t *testing.T) {
	home := t.TempDir()
	t.Setenv("HOME", home)
	t.Setenv("USERPROFILE", home)
	dir := filepath.Join(run.Runs(), "fix-api")
	if err := os.MkdirAll(dir, 0o700); err != nil {
		t.Fatal(err)
	}
	current := run.Fields("state", "interrupted", "pid", 123)
	if err := run.Create(dir, current); err != nil {
		t.Fatal(err)
	}
	code, why, err := ResumeExpected("fix-api", run.Fields("state", "waiting", "pid", 122), nil, nil)
	after, _ := run.Read(dir)
	if code != 2 || why != loop.ErrChanged.Error() || err != nil || after.Str("state") != "interrupted" || !run.Equal(after.Get("pid"), run.Number("123")) {
		t.Fatalf("resume adopted another attempt: %d, %q, %v, %s", code, why, err, run.Line(after))
	}
}

func TestAnOrderToAResumeLeftToPythonIsNeverWritten(t *testing.T) {
	home := t.TempDir()
	t.Setenv("HOME", home)
	t.Setenv("USERPROFILE", home)
	dir := filepath.Join(run.Runs(), "fix-api")
	if err := os.MkdirAll(dir, 0o700); err != nil {
		t.Fatal(err)
	}
	if err := run.Create(dir, run.Fields("state", "running", "worktree", t.TempDir())); err != nil {
		t.Fatal(err)
	}
	read, _ := run.Read(dir)
	before, _ := os.ReadFile(filepath.Join(dir, "run.json"))
	// no task.md: Python's resume to make
	_, _, err := ResumeExpected("fix-api", read, func(record *run.Object) { record.Set("stall_resume_at", 1) }, nil)
	after, _ := os.ReadFile(filepath.Join(dir, "run.json"))
	if !errors.Is(err, ErrPython) || string(after) != string(before) {
		t.Fatalf("%v: %s", err, after)
	}
}
