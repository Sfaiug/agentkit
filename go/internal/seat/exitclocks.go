package seat

import (
	"time"

	"agentkit/internal/run"
	"agentkit/internal/tmux"
)

// SeenEvery is how long a live or attached seat goes before another stamp (orch.SEEN_EVERY).
const SeenEvery = 300

func stampExited(name string, now time.Time) error {
	said, err := tmux.Ask(tmux.Own(), "display-message", "-p", "-t", "="+name+":", "#{session_attached}")
	if err != nil {
		return err
	}
	return Update(name, func(record *run.Object) bool {
		if said != "0" {
			seen, dated := record.Num("seen")
			if record.Truthy("exited_since") || !dated || float64(now.Unix())-seen > SeenEvery {
				record.Set("seen", int(now.Unix()))
				record.Delete("exited_since")
				return true
			}
		} else if !record.Truthy("exited_since") {
			record.Set("exited_since", int(now.Unix()))
			return true
		}
		return false
	})
}
