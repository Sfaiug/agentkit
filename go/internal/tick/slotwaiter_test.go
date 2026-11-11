//go:build linux

package tick

import (
	"os/exec"
	"path/filepath"
	"testing"
	"time"

	"agentkit/internal/config"
	"agentkit/internal/host"
	"agentkit/internal/run"
)

// A slot waiter whose process died inside its launch's grace is left by the dead-loops pass; the
// stall row starts it again in a new process, still waiting, its place in line kept, as Python's does.
func TestASlotWaiterDeadInItsLaunchGraceWaitsAgainInANewProcess(t *testing.T) {
	dir, _, tick := stalledRun(t, "exit 0")
	ended := exec.Command("true")
	if err := ended.Run(); err != nil {
		t.Fatal(err)
	}
	now, pid := epoch(tick.clock()), ended.ProcessState.Pid()
	put(t, filepath.Join(dir, "task.md"), "---\nrepo: none\n---\n# Retry\n\n## Done when\n```bash\ntrue\n```\n")
	put(t, filepath.Join(dir, "run.json"), run.Line(run.SetAll(run.Capture(dir, "", nil, map[string]bool{"--no-merge": true},
		config.Binding{}, ""), "state", "queued", "slot_waiting", true, "launch_pending", true, "queued_at", now-10,
		"pid", pid, "scratch", true, "no_merge", true, "scope", "none")))
	before := read(t, filepath.Join(dir, "run.json"))
	if err := tick.deadLoops(); err != nil || read(t, filepath.Join(dir, "run.json")) != before {
		t.Fatalf("the dead-loops pass took it: %v\n%s", err, read(t, filepath.Join(dir, "run.json")))
	}
	if err := tick.stallRecovery(); err != nil {
		t.Fatal(err)
	}
	after, _ := run.Read(dir)
	queued, _ := after.Num("queued_at")
	again, _ := after.Int("pid")
	// the new process writes into this HOME: it ends before the HOME goes
	t.Cleanup(func() {
		for deadline := time.Now().Add(10 * time.Second); time.Now().Before(deadline); time.Sleep(5 * time.Millisecond) {
			if stat, known := host.ReadStat(again); !known || stat.Exited() {
				return
			}
		}
	})
	if after.Str("state") != "queued" || !after.Truthy("slot_waiting") || queued != now-10 || again == 0 || again == pid {
		t.Fatalf("not waiting again in a new process:\n%s", run.Line(after))
	}
}
