package launch

import (
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
	code, why, err := ResumeExpected("fix-api", run.Fields("state", "waiting", "pid", 122))
	after, _ := run.Read(dir)
	if code != 2 || why != loop.ErrChanged.Error() || err != nil || after.Str("state") != "interrupted" || !run.Equal(after.Get("pid"), run.Number("123")) {
		t.Fatalf("resume adopted another attempt: %d, %q, %v, %s", code, why, err, run.Line(after))
	}
}
