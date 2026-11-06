package launch

import (
	"agentkit/internal/history"
	"agentkit/internal/run"
)

// recorded writes the launch's row in history.db, as Python's capture_launch does once its receipt
// stands, a failure said in history.log.
func recorded(dir string) {
	if record, _ := run.Read(dir); record != nil {
		history.Start(record, nil)
	}
}
