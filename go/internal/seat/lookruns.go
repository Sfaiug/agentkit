package seat

import (
	"time"

	"agentkit/internal/run"
)

// Looks and menu frames use the same read-only interpretation of full run records.
// Maintenance belongs to the tick rows that reap or offer those endings.
// The shared ladder keeps a running task ahead of news about its endings.
func lookRuns(_ []string, now time.Time) (map[string][]ran, bool) {
	runs, _, known := menuRuns(now, new(run.Reader))
	return runs, known
}
