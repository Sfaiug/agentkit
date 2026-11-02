package task

import (
	"cmp"
	"regexp"
	"strings"

	"agentkit/internal/config"
)

var unslug = regexp.MustCompile(`[^a-z0-9]+`)

// Slug is Python's slugify: Python lowers İ to i and a combining dot, Go to i alone.
func Slug(title string) string {
	slug := unslug.ReplaceAllString(strings.ToLower(strings.ReplaceAll(title, "İ", "i̇")), "-")
	slug = strings.Trim(slug, "-")
	return cmp.Or(strings.Trim(slug[:min(len(slug), 40)], "-"), "task")
}

// WithoutFront is AGENTS.md text past its front matter.
func WithoutFront(text string) string {
	if at := agentsRe.FindStringIndex(text); at != nil {
		return text[at[1]:]
	}
	return text
}

// Group is a command list split on the `# once` marker, markers stripped, Python's group_commands.
func Group(cmds []string) (every, once []string) {
	for _, cmd := range cmds {
		if bare, marked := SplitOnce(cmd); marked {
			once = append(once, bare)
		} else {
			every = append(every, bare)
		}
	}
	return every, once
}

// RoundCommands is the done-when as a round runs it, Python's round_commands: a run that does not
// land runs each line every round, its mark stripped; one that lands has the declared suite, ""
// for none, as its one `# once` line, however the task names it.
func RoundCommands(cmds []string, suite string, landing bool) []string {
	var kept []string
	if !landing {
		for _, cmd := range cmds {
			bare, _ := SplitOnce(cmd)
			kept = append(kept, bare)
		}
		return kept
	}
	if suite == "" {
		return cmds
	}
	targets := map[string]bool{collapsed(suite): true}
	if first := collapsed(firstCommand(suite)); first != "" {
		targets[first] = true
	}
	for _, cmd := range cmds {
		bare, marked := SplitOnce(cmd)
		if marked && bare != suite || !marked && !targets[collapsed(bare)] {
			kept = append(kept, cmd)
		}
	}
	return append(kept, suite+"  # once")
}

func collapsed(text string) string {
	return strings.Join(strings.FieldsFunc(text, config.Space), " ")
}

// firstCommand is the shell line up to its first output plumbing outside any quotes and any
// `$(...)`, Python's first_command: a task ends its done-when with the suite's bare command while
// the repository declares it with its log plumbing, and the two are the same run.
func firstCommand(cmd string) string {
	single, double, escaped, depth := false, false, false, 0
	for i := 0; i < len(cmd); i++ {
		c := cmd[i]
		switch {
		case escaped:
			escaped = false
		case c == '\\' && !single:
			escaped = true
		case c == '\'' && !double:
			single = !single
		case c == '"' && !single:
			double = !double
		case single || double:
		case c == '$' && i+1 < len(cmd) && cmd[i+1] == '(':
			depth++
			i++
		case c == ')' && depth > 0:
			depth--
		case depth > 0:
		case strings.HasPrefix(cmd[i:], "2>&1"), c == '|', c == ';', strings.HasPrefix(cmd[i:], "&&"):
			return cmd[:i]
		}
	}
	return cmd
}

// FrontLines is the lines of AGENTS.md front matter that say something: neither blank nor a comment.
func FrontLines(text string) []string {
	match := agentsRe.FindStringSubmatch(text)
	if match == nil {
		return nil
	}
	var found []string
	for _, line := range config.SplitLines(match[1]) {
		trimmed := strings.TrimFunc(line, config.Space)
		if trimmed != "" && !strings.HasPrefix(trimmed, "#") {
			found = append(found, trimmed)
		}
	}
	return found
}
