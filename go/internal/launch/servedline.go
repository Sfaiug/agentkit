package launch

import (
	"fmt"
	"path/filepath"
	"slices"
	"time"

	"agentkit/internal/job"
	"agentkit/internal/plan"
	"agentkit/internal/run"
)

func missingPlanLine(path string) string {
	return filepath.Base(path) + `: none of its ## Done when checks match an open plan line (your plan is what your bar counts): first run ak plan add "<outcome>" --check '<focused-check>' and put that same check in ## Done when`
}

// ClaimedPlanLines reads the active run and unfinished job receipts of the seat.
func ClaimedPlanLines(seat string) map[string]string {
	taken := map[string]string{}
	if seat == "" {
		return taken
	}
	now, owner := time.Now(), run.Seats()
	read := run.EveryShared(func(dir string, r *run.Object) bool {
		if line := r.Str("plan_line"); line != "" && !run.Ended(r) && r.Str("state") != "exhausted" && owner(r) == seat && run.Going(r, now) {
			taken[line] = filepath.Base(dir)
		}
		return true
	})
	jobs, ok := job.Listed(seat, true, now)
	if !ok || !read {
		return nil
	}
	for _, j := range jobs {
		if j.Receipt.Truthy("finished_at") {
			continue
		}
		for _, item := range j.Receipt.List("tasks") {
			if task, ok := item.(*run.Object); ok && task.Str("plan_line") != "" && !slices.Contains(job.Terminal, task.Str("state")) {
				taken[task.Str("plan_line")] = task.Str("name")
			}
		}
	}
	return taken
}

func servedLine(seat, path string, checks []string, taken map[string]string) (any, error) {
	if seat == "" {
		return nil, nil
	}
	line, err := plan.ServedLine(seat, checks, taken)
	switch {
	case err != nil:
		return nil, ErrPython
	case line == "":
		return nil, nil
	}
	name := filepath.Base(path)
	if owner, held := taken[line]; held {
		return nil, &refusedOutright{fmt.Sprintf(`%s: %s already serves %s; add a separate open plan line with ak plan add "<outcome>" --check '<focused-check>' and put that same check in ## Done when`, name, owner, line)}
	}
	if taken != nil {
		taken[line] = name
	}
	return line, nil
}
