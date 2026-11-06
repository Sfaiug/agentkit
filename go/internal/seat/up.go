package seat

import (
	"strings"

	"agentkit/internal/tmux"
)

// Up is each seat a line can go into now (Watching), by name, with its tmux birth: orch.sessions'
// `created`, which a typed line's mark names its seat by.
func Up() map[string]int {
	up := map[string]int{}
	said, err := tmux.Ask(tmux.Own(), "list-sessions", "-F", "#{session_name}\t#{"+tmux.Mark+"}\t#{session_created}")
	if err != nil {
		return up
	}
	for _, line := range strings.Split(said, "\n") {
		if fields := strings.Split(line, "\t"); len(fields) == 3 && fields[1] == "1" {
			if _, exited := harnessScreen(fields[0]); !exited {
				up[fields[0]] = created(fields[2])
			}
		}
	}
	return up
}
