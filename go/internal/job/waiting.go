package job

import (
	"os"
	"path/filepath"
	"slices"

	"agentkit/internal/config"
	"agentkit/internal/run"
)

// Terminal are the task states a job is done with (job.JOB_TERMINAL).
var Terminal = []string{"merged", "passed", "failed", "blocked", "skipped", "stopped"}

// Waiting is whether a live job of the seat's is one it can wait on, before any task of it has a
// run (job.job_waiting): finished, or its launcher still running, with a task not done.
func Waiting(seat string) bool {
	entries, _ := os.ReadDir(Jobs())
	for _, entry := range entries {
		job, _ := run.ReadJSON(filepath.Join(Jobs(), entry.Name(), "job.json"))
		if job == nil || job.Str("seat") == "" {
			continue
		}
		if owner, _, err := config.ResolveSession(job.Str("seat")); job.Str("seat") != seat && (err != nil || owner != seat) {
			continue
		}
		if !job.Truthy("finished_at") && !run.ProcessActive(job) {
			continue
		}
		if slices.ContainsFunc(job.List("tasks"), func(task any) bool {
			listed, _ := task.(*run.Object)
			return listed != nil && !slices.Contains(Terminal, listed.Str("state"))
		}) {
			return true
		}
	}
	return false
}
