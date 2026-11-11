package cli

import (
	"fmt"
	"io"
	"time"

	"agentkit/internal/config"
	"agentkit/internal/job"
	"agentkit/internal/run"
)

// tasks are the runs the jobs' tasks name, which the listing reads and reaps as it does its own.
func tasks(jobs []job.Shown) map[string]bool {
	named := map[string]bool{}
	for _, shown := range jobs {
		for _, id := range shown.Runs() {
			named[id] = true
		}
	}
	return named
}

// printJobs is each job's block, its tasks' runs as the listing reaped them.
func printJobs(out io.Writer, jobs []job.Shown, entries []listed, models map[string]config.Model, index run.Index, now time.Time) {
	reaped := map[string]*run.Object{}
	for _, entry := range entries {
		if !entry.unreadable {
			reaped[entry.name()] = entry.record
		}
	}
	for _, shown := range jobs {
		for _, line := range shown.Block(func(id string) *run.Object { return reaped[id] }, models, index, now) {
			fmt.Fprintln(out, line)
		}
	}
}
