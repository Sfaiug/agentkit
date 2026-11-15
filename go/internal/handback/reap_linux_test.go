package handback

import (
	"os"
	"os/exec"
	"path/filepath"
	"testing"
	"time"

	"agentkit/internal/config"
	"agentkit/internal/host"
	"agentkit/internal/run"
)

// A going run whose loop is gone while a process of the run still runs is left as it was, for
// Python's reap, which stops a running loop's and leaves a queued launch's at work.
func TestAGoingRunWithAProcessLeftIsNotInterrupted(t *testing.T) {
	home := config.Resolve(t.TempDir())
	t.Setenv("HOME", home)
	dir := filepath.Join(run.Runs(), "acme-launch")
	if err := os.MkdirAll(dir, 0o700); err != nil {
		t.Fatal(err)
	}
	worker := exec.Command("sleep", "60")
	worker.Env = append(os.Environ(), host.Marker+"="+dir)
	if err := worker.Start(); err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { worker.Process.Kill(); worker.Wait() })
	// Start returns once the exec is under way, which on a loaded host can be before /proc shows
	// the environment the worker is marked by
	for deadline := time.Now().Add(10 * time.Second); !run.Working(dir); time.Sleep(10 * time.Millisecond) {
		if time.Now().After(deadline) {
			t.Fatal("the worker never showed its marker")
		}
	}
	now := seconds()
	for _, state := range []string{"queued", "running"} {
		planted := run.Fields("run_id", "acme-launch", "state", state, "queued_at", run.Float(now-3600), "started_at", run.Float(now-3600))
		if err := os.WriteFile(filepath.Join(dir, "run.json"), []byte(run.Line(planted)), 0o600); err != nil {
			t.Fatal(err)
		}
		read, _ := run.Read(dir)
		reaped, err := Interrupt(dir, read, now)
		if after, _ := run.Read(dir); reaped || err != nil || run.Line(after) != run.Line(planted) {
			t.Errorf("a %s run with a process left was reaped: %s %v", state, run.Line(after), err)
		}
	}
}
