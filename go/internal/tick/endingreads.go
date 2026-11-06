package tick

import (
	"time"

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

// An unfinished run can protect its seat from retirement; settled runs protect none.
func noRunSweep() bool {
	return run.Every(func(_ string, record *run.Object) bool {
		return (!run.Active(record) || goingOn(record, epoch(time.Now()))) &&
			(record.Str("state") == "interrupted" || run.Ended(record) || !run.NeedsRecovery(record) || record.Truthy("recovery_acknowledged_at"))
	})
}
