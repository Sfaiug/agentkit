package loop

import (
	"io"
	"path/filepath"

	"agentkit/internal/run"
)

// ParkedLine is the line the run waits in with no process of its own, "" for none (landing_line).
func ParkedLine(record *run.Object) string {
	if !parkedInLine(record) {
		return ""
	}
	return landingLine(record)
}

// StartLine starts a lander on that line where none runs and a member waits, as start_line does
// for the tick: a line under no `.merge-` name of runs/ starts nothing.
func StartLine(line string, said io.Writer) { startLine(filepath.Join(run.Runs(), line), said) }
