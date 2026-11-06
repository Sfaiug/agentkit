package tick

import (
	"agentkit/internal/config"
	"agentkit/internal/run"
)

// Revival files projectless seats from run evidence even when no run is still going.
func noRunRevival() bool {
	return run.Every(func(_ string, record *run.Object) bool {
		name := run.Seat(record)
		if name == "" || !record.Truthy("repo") {
			return true
		}
		_, seat, err := config.ResolveSession(name)
		return err == nil && (seat["repo"] != nil && seat["repo"] != "" || seat["filed"] == true)
	})
}
