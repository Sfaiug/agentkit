package seat

import "time"

// Exited is every seat tmux still holds whose panes have all exited (orch.sessions' `exited`), which
// Health publishes as gone without its look; false where the home holds a seat Go does not read.
func Exited(now time.Time) ([]string, bool) {
	home, known := seated(now)
	var names []string
	for _, each := range home.Seats {
		if each.held {
			names = append(names, each.Name)
		}
	}
	return names, known
}
