// Package task reads the files a task is written in as Python ak does: the task's front
// matter and done-when commands, and the front matter of a repository's AGENTS.md.
package task

import (
	"os"
	"regexp"
	"slices"
	"strings"
)

var (
	doneWhen = regexp.MustCompile(`(?ims)^##\s+Done when\s*$(.*?)(?:^##\s|\z)`)
	fence    = regexp.MustCompile("(?s)```(?:bash|sh)?\n(.*?)```")
	frontRe  = regexp.MustCompile(`(?s)^---\n(.*?)\n---\n?(.*)$`)
	agentsRe = regexp.MustCompile(`(?s)^---\n(|.*?\n)---`)
	onceRe   = regexp.MustCompile(`^#\s*once\s*$`)
)

var taskKeys = []string{"after", "base", "done_when_minutes", "files", "from", "merge", "repo",
	"rounds", "stall_minutes", "target", "turn_hours"}

// DoneWhen is the task's done-when commands, or false where the task is unreadable.
func DoneWhen(path string) ([]string, bool) {
	data, err := os.ReadFile(path)
	if err != nil {
		return nil, false
	}
	text := Text(data)
	body := text
	if match := frontRe.FindStringSubmatch(text); match != nil {
		for _, line := range strings.Split(match[1], "\n") {
			line = strings.TrimSpace(line)
			if line == "" || strings.HasPrefix(line, "#") {
				continue
			}
			key, _, found := strings.Cut(line, ":")
			if !found || !slices.Contains(taskKeys, strings.TrimSpace(key)) {
				return nil, false
			}
		}
		body = match[2]
	} else if strings.HasPrefix(text, "---\n") {
		return nil, false
	}
	section := doneWhen.FindStringSubmatch(body)
	if section == nil {
		return nil, false
	}
	block := fence.FindStringSubmatch(section[1])
	if block == nil {
		return nil, false
	}
	var cmds []string
	for _, line := range strings.Split(block[1], "\n") {
		if line = strings.TrimSpace(line); line != "" && !strings.HasPrefix(line, "#") {
			cmds = append(cmds, line)
		}
	}
	return cmds, len(cmds) > 0
}

// Once is whether a command ends in a `# once` marker outside any quotes.
func Once(cmd string) bool {
	single, double, escaped := false, false, false
	for i, ch := range cmd {
		switch {
		case escaped:
			escaped = false
		case ch == '\\' && !single:
			escaped = true
		case ch == '\'' && !double:
			single = !single
		case ch == '"' && !single:
			double = !double
		case ch == '#' && !single && !double:
			if i > 0 && (cmd[i-1] == ' ' || cmd[i-1] == '\t') && onceRe.MatchString(cmd[i:]) {
				return true
			}
		}
	}
	return false
}

// FrontValue is a key's value in AGENTS.md front matter, or "".
func FrontValue(text, key string) string {
	match := agentsRe.FindStringSubmatch(text)
	if match == nil {
		return ""
	}
	for _, line := range strings.Split(match[1], "\n") {
		name, value, found := strings.Cut(strings.TrimSpace(line), ":")
		if found && strings.TrimSpace(name) == key && strings.TrimSpace(value) != "" {
			return strings.TrimSpace(value)
		}
	}
	return ""
}

// Text is text as Python reads a text file or a command's output: every line ending a
// newline.
func Text(data []byte) string {
	return strings.NewReplacer("\r\n", "\n", "\r", "\n").Replace(string(data))
}
