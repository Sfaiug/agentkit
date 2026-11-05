package tick

import (
	"path/filepath"

	"agentkit/internal/run"
)

// Only these runs defer gone-seat recovery to automatic run revival.
func revivalRuns() (map[string]string, bool) {
	going := map[string]string{}
	known := run.Every(func(dir string, record *run.Object) bool {
		if name := run.Seat(record); name != "" && run.Active(record) && going[name] == "" {
			going[name] = filepath.Base(dir)
		}
		return true
	})
	return going, known
}
