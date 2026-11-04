package seat

import "time"

// FileProjects gives the tick the same run votes and locked filing as the menu.
func FileProjects(now time.Time) bool {
	runs, projects, known := menuRuns(now)
	return known && menuProjects(runs, projects)
}
