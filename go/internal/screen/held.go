package screen

import (
	"strings"

	"agentkit/internal/config"
)

// Held is the background work the tail shows running (watch.screen_holds): for each row of the
// manifest's `held` group of a name, that name, in Claude's terms.  False where it cannot tell:
// no `held` to read, or a screen not drawn as it reads, too narrow for it or under a dialog.
func (r *Rules) Held(tail string) ([]string, bool) {
	if r.held == nil {
		return nil, false
	}
	var lines []string
	for _, line := range config.SplitLines(tail) {
		if plain := Plain(line); plain != "" {
			lines = append(lines, plain)
		}
	}
	found := r.held.Find(strings.Join(lines, "\n"))
	if found == nil {
		return nil, false
	}
	held := []string{}
	for _, kind := range r.held.Names() {
		rows, _ := found.Group(kind)
		for range config.SplitLines(rows) {
			held = append(held, kind)
		}
	}
	return held, true
}
