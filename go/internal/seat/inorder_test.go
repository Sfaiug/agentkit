package seat

import (
	"os"
	"path/filepath"
	"testing"

	"agentkit/internal/job"
	"agentkit/internal/run"
)

// An ordered job's one line says the endings of its tasks up to its own; a task resumed after it
// ended says its own, as Python's job.in_order.
func TestInOrderEndsAtTheJobsEnding(t *testing.T) {
	home := t.TempDir()
	t.Setenv("HOME", home)
	t.Setenv("USERPROFILE", home)
	dir := filepath.Join(job.Jobs(), "batch")
	if err := os.MkdirAll(dir, 0o700); err != nil {
		t.Fatal(err)
	}
	for _, c := range []struct {
		job, run any
		want     bool
	}{{nil, 110, true}, {100, nil, true}, {100, 90, true}, {100, 100, true}, {100, 110, false}} {
		if err := job.Write(dir, run.Fields("job_id", "batch", "finished_at", c.job,
			"opts", run.Fields("--in-order", true), "tasks", []any{})); err != nil {
			t.Fatal(err)
		}
		if got := inOrder(run.Fields("job_id", "batch", "finished_at", c.run)); got != c.want {
			t.Errorf("job ended %v, run %v: inOrder=%v, want %v", c.job, c.run, got, c.want)
		}
	}
}
