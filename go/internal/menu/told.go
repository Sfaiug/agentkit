package menu

import "agentkit/internal/terminal"

// Told is text said on lines of its own under a page's rows, Python's config_limits' told: a blank
// line, then text wrapped at a word, each line indented.
func Told(s terminal.Screen, text string) []string {
	lines := []string{""}
	for _, part := range terminal.Wrap(text, s.LayoutWidth()-2) {
		lines = append(lines, "  "+part)
	}
	return lines
}
