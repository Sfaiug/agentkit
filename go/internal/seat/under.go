package seat

import (
	"cmp"
	"path/filepath"
	"slices"
	"strings"
	"sync"

	"agentkit/internal/config"
	"agentkit/internal/run"
	"agentkit/internal/tmux"
)

// Under is the open seats filed under that checkout, newest first, as Python's retire.seats_for
// reads them: each session tmux holds as a seat (orch.sessions), not all its panes dead, whose
// record's repo is that checkout, by when tmux opened it, then by name.
func Under(checkout string) []string {
	state := filepath.Join(config.Home(), "state")
	_, seats := holdings(state)
	stands := sync.OnceValue(listed)
	born, dead := map[string]int{}, map[string][]string{}
	var found []string
	for name, server := range seats {
		if _, asked := dead[server]; !asked {
			dead[server] = tmux.Dead(server)
			said, _ := tmux.Ask(server, "list-sessions", "-F", "#{session_name}\t#{session_created}")
			for _, line := range strings.Split(said, "\n") {
				if session, at, ok := strings.Cut(line, "\t"); ok && seats[session] == server {
					born[session] = created(at)
				}
			}
		}
		record, _ := run.ReadJSON(filepath.Join(state, "session-"+name+".json"))
		if !slices.Contains(dead[server], name) && record != nil && !record.Has(config.Renamed) &&
			checkoutOf(record.Str("repo"), stands) == checkout {
			found = append(found, name)
		}
	}
	slices.SortFunc(found, func(a, b string) int { return cmp.Or(cmp.Compare(born[b], born[a]), strings.Compare(b, a)) })
	return found
}
