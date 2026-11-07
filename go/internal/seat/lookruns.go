package seat

import "agentkit/internal/run"

// Looks and menu frames use the same read-only interpretation of full run records.
// Maintenance belongs to the tick rows that reap or offer those endings.
// The shared ladder keeps a running task ahead of news about its endings.
func lookRuns([]string) judges {
	held, known := new(run.Reader).Read()
	if !known {
		return unreadRuns
	}
	return judging(held)
}
