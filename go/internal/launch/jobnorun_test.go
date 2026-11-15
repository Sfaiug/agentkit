//go:build linux

package launch

import (
	"os"
	"os/exec"
	"slices"
	"testing"
	"time"

	"agentkit/internal/job"
	"agentkit/internal/run"
)

// A relaunched job's task its launcher saved running and died before it filed a run, its run_id
// null or absent, is queued with no run before any task starts, and waits for room like any queued
// task: with room for one run, held by the job's other member running on a run alive elsewhere, no
// second run starts.  The task comes first, so by the time the member's take-up looks again later
// (retry_after), the scheduler has passed it over.
func TestARunningTaskWithNoRunWaitsForRoom(t *testing.T) {
	for name, noRun := range map[string]func(*run.Object){
		"null":   func(task *run.Object) { task.Set("run_id", nil) },
		"absent": func(task *run.Object) { task.Delete("run_id") },
	} {
		t.Run(name, func(t *testing.T) {
			jobHome(t)
			j := createdJob(t, "fix-api.md", "fix-db.md")
			held(t, "20261109-0900-fix-db")
			tasks := j.receipt.List("tasks")
			lost, live := tasks[0].(*run.Object), tasks[1].(*run.Object)
			run.SetAll(lost, "state", "running", "started_at", run.Float(seconds()))
			noRun(lost)
			run.SetAll(live, "state", "running", "run_id", "20261109-0900-fix-db")
			run.SetAll(j.receipt, "parallel", 1, "pid", died(t))
			if err := job.Save(j.dir, j.receipt); err != nil {
				t.Fatal(err)
			}
			launcher := exec.Command(os.Args[0], "run", "resume", j.id())
			if err := launcher.Start(); err != nil {
				t.Fatal(err)
			}
			t.Cleanup(func() { launcher.Process.Kill(); launcher.Wait() })
			receipt := j.receipt
			for deadline := time.Now().Add(30 * time.Second); !receipt.List("tasks")[1].(*run.Object).Truthy("retry_after"); time.Sleep(20 * time.Millisecond) {
				if time.Now().After(deadline) {
					t.Fatalf("the member was never looked at: %s", run.Line(receipt))
				}
				receipt, _ = job.Read(j.dir)
			}
			lost = receipt.List("tasks")[0].(*run.Object)
			var runs []string
			entries, _ := os.ReadDir(run.Runs())
			for _, entry := range entries {
				if entry.IsDir() {
					runs = append(runs, entry.Name())
				}
			}
			if lost.Str("state") != "queued" || !lost.Has("run_id") || lost.Get("run_id") != nil ||
				!slices.Equal(runs, []string{"20261109-0900-fix-db"}) {
				t.Fatalf("a second run started: %s, runs %v", run.Line(receipt), runs)
			}
		})
	}
}
