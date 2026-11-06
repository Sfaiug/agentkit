package screen

import (
	"slices"
	"unicode/utf8"

	"agentkit/internal/config"
)

// reach is every row a ruled composer's draft may reach up to: the tail's, and above them the
// pane's where the harness scrolls a draft taller than its box inside it, so its box, prompt row
// first, is whole on the screen however tall the draft (`[screen] scrolls`).
func (r *Rules) reach(pane string, tail []string) []string {
	if !r.scrolls {
		return tail
	}
	above := contentRows(pane)
	return slices.Concat(above[:max(0, len(above)-tailRows)], tail)
}

// upToPrompt is the last `count` rows, and above them the rows a draft taller than those goes on
// in, indented under its prompt row, up to that row: raw, and as read (watch.screen_state).
func upToPrompt(rows []string, count int) ([]string, []string) {
	top := len(rows) - count
	for top > 0 {
		if first, _ := utf8.DecodeRuneInString(strip(rows[top])); !config.Space(first) {
			break
		}
		top--
	}
	return rows[top:], plains(rows[top:])
}
