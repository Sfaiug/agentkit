package screen

import (
	"strings"

	"agentkit/internal/config"
)

// Held is the background work the tail shows running (watch.screen_holds): for each row of the
// manifest's `held` group of a name, that name, the type a Stop's list gives such work.  False
// where it cannot tell: no `held` to read, or a screen not drawn as it reads, too narrow for it or
// under a dialog.
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
	text := strings.Join(lines, "\n")
	found := r.held.Find(text)
	if found == nil {
		return nil, false
	}
	held := []string{}
	for _, kind := range r.held.Names() {
		start, end, _ := found.Group(kind)
		for range config.SplitLines(text[start:end]) {
			held = append(held, kind)
		}
	}
	return held, true
}
