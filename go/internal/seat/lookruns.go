package seat

import (
	"time"

	"agentkit/internal/run"
)

// Looks and menu frames use the same read-only interpretation of full run records.
// Maintenance belongs to the tick rows that reap or offer those endings.
func lookRuns(_ []string, now time.Time) (map[string][]ran, bool) {
	runs, _, known := menuRuns(now)
	for _, mine := range runs {
		for _, each := range mine {
			// The menu can list these records, but a look cannot yet decide which
			// endings news_owed must keep working instead of publishing done.
			if run.OwesEnding(each.record, now) {
				return nil, false
			}
		}
	}
	return runs, known
}
