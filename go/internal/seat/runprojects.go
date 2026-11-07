package seat

import (
	"time"

	"agentkit/internal/run"
)

// FileProjects gives the tick the same run votes and locked filing as the menu.
func FileProjects(now time.Time) bool {
	held, known := new(run.Reader).Read()
	if !known {
		return false
	}
	runs, projects, known := menuRuns(held, now)
	if !known {
		return false
	}
	_, known = menuProjects(runs, projects)
	return known
}
