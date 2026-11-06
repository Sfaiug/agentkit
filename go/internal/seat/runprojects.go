package seat

import (
	"time"

	"agentkit/internal/run"
)

// FileProjects gives the tick the same run votes and locked filing as the menu.
func FileProjects(now time.Time) bool {
	runs, projects, known := menuRuns(now, new(run.Reader))
	if !known {
		return false
	}
	_, known = menuProjects(runs, projects)
	return known
}
