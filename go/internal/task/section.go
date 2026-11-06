package task

import (
	"regexp"
	"strings"

	"agentkit/internal/config"
)

var (
	fenceMark = regexp.MustCompile("^ {0,3}(`{3,}|~{3,})(.*)")
	anySecond = regexp.MustCompile(`^##[ \t]+`)
)

// Section is the text under a task body's first `## <heading>`, Python's goal_text: its
// indentation and examples kept, as a heading inside a fenced block is the section's text.
func Section(body, heading string) string {
	if found := sections(body, heading); len(found) > 0 {
		return found[0]
	}
	return ""
}

// sections is the text under each `## <heading>` of a task body, in order, Python's _sections.
func sections(body, heading string) []string {
	named := regexp.MustCompile(`(?i)^##[ \t]+` + regexp.QuoteMeta(heading) + `[ \t]*$`)
	var all, lines []string
	found, fence := false, ""
	for _, line := range config.SplitLines(body) {
		marker := fenceMark.FindStringSubmatch(line)
		switch {
		case fence != "":
			if marker != nil && strings.HasPrefix(marker[1], fence) && strings.TrimFunc(marker[2], config.Space) == "" {
				fence = ""
			}
		case marker != nil && (marker[1][0] == '~' || !strings.Contains(marker[2], "`")):
			fence = marker[1]
		case anySecond.MatchString(line):
			if found {
				all = append(all, strings.Trim(strings.Join(lines, "\n"), "\n"))
			}
			found, lines = named.MatchString(line), nil
			continue
		}
		if found {
			lines = append(lines, line)
		}
	}
	if found {
		all = append(all, strings.Trim(strings.Join(lines, "\n"), "\n"))
	}
	return all
}
