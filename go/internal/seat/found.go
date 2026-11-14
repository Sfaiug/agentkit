package seat

import "agentkit/internal/config"

// Found is whether tmux holds that seat up for a line, as Python's after_merge_live reads
// orch.find: held, and not all its panes exited.  Not known where its name cannot be followed, or
// the seat is on the person's own server, from before ak had its own.
func Found(name string) (up, known bool) {
	name, record, err := config.ResolveSession(name)
	if err != nil {
		return false, false
	}
	held, exited, known := find(name, record)
	return held && !exited, known
}
