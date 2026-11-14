package harness

import "agentkit/internal/config"

// TitleLine is the line that gives a seat of that harness the name it has as its title (its
// plugin's `title_command`), and whether the harness's own title, unread, confirms it once the
// line has gone in (`[title] unreadable`); "" where Go types no title into its seats.
func TitleLine(own, name string) (string, bool) {
	line := plugins[own].titleLine
	facts, err := config.Section(own, "title")
	if line == nil || err != nil {
		return "", false
	}
	unreadable, set := facts["unreadable"].(bool)
	return line(name), unreadable || !set
}

// claudeTitleLine is claude.py's `title_command`: Remote Control takes /rename live.
func claudeTitleLine(name string) string { return "/rename " + name }
