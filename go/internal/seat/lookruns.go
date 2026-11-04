package seat

import (
	"slices"
	"time"

	"agentkit/internal/run"
)

// Looks and menu frames use the same read-only interpretation of full run records.
// Maintenance belongs to the tick rows that reap or offer those endings.
func lookRuns(_ []string, now time.Time) (map[string][]ran, bool) {
	runs, _, known := menuRuns(now)
	for _, mine := range runs {
		// A running task keeps the seat working before its endings can decide a word.
		if slices.ContainsFunc(mine, func(each ran) bool { return each.view.going }) {
			continue
		}
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
