package handback

import (
	"os"
	"os/exec"
	"path/filepath"
	"testing"

	"agentkit/internal/config"
	"agentkit/internal/run"
)

// A queued launch and a running loop whose processes are gone are interrupted as Python's reap
// leaves them, field by field but for the time it noticed: what handback.reap wrote of these two
// records in a fresh home.
func TestAGoingRunWithNoProcessIsInterrupted(t *testing.T) {
	home := config.Resolve(t.TempDir())
	t.Setenv("HOME", home)
	t.Setenv("USERPROFILE", home)
	gone := exec.Command(os.Args[0], "-test.run=^$")
	if err := gone.Run(); err != nil {
		t.Fatal(err)
	}
	now := seconds()
	for _, each := range []struct {
		planted *run.Object
		reason  string
	}{
		{run.Fields("run_id", "acme-queued", "state", "queued", "title", "Fix api", "queued_at", run.Float(now-3600), "launch_pending", true),
			"Queued launcher exited before starting work."},
		{run.Fields("run_id", "acme-running", "state", "running", "title", "Fix api", "started_at", run.Float(now-3600), "pid", gone.Process.Pid, "step", "executor"),
			"Run process exited or its identity changed."},
	} {
		dir := filepath.Join(run.Runs(), each.planted.Str("run_id"))
		// as a test plants it, not as a write leaves it
		if os.MkdirAll(dir, 0o700) != nil || os.WriteFile(filepath.Join(dir, "run.json"), []byte(run.Line(each.planted)), 0o600) != nil {
			t.Fatal("cannot plant ", dir)
		}
		read, _ := run.Read(dir)
		if reaped, err := Interrupt(dir, read, now); !Interruptible(read, now) || !reaped || err != nil {
			t.Fatalf("%s was not reaped: %v", dir, err)
		}
		after, _ := run.Read(dir)
		want := run.SetAll(each.planted.Copy(), "state", "interrupted", "interrupted_at", after.Get("interrupted_at"),
			"interruption_reason", each.reason, "recovery_pending", true, "silence_minutes", 20, "ceiling_hours", 6)
		if at, dated := after.Num("interrupted_at"); !dated || at != now || run.Line(after) != run.Line(want) {
			t.Errorf("reaped as\n%s\nnot as Python's reap leaves it\n%s", run.Line(after), run.Line(want))
		}
	}
}
