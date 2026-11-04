package seat

import (
	"path/filepath"
	"time"

	"agentkit/internal/config"
)

// StopCount offers the popup's card only where Stop carries its own seat. It reads the same
// admission as Stop, without reconciling records, taking locks or writing a stop mark.
func StopCount(name string, now time.Time) (int, bool) {
	current, _, err := config.CurrentSession()
	if err != nil || current == "" || current != name {
		return 0, false
	}
	found, known := look(filepath.Join(config.Home(), "state"), name, now)
	return len(found.going), known && (found.live || found.recorded)
}
