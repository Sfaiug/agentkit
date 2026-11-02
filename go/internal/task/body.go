package task

import (
	"os"
	"regexp"
	"strings"
	"unicode/utf8"

	"agentkit/internal/config"
)

// Body is a task's text after its front matter, as Python's parse_task reads it.
func Body(text string) string {
	if match := frontRe.FindStringSubmatch(text); match != nil {
		return match[2]
	}
	return text
}

// Files is the Git pathspecs of a task's repeatable, comma-separated `files:` lines, Python's
// task_files.
func Files(text string) []string {
	match := frontRe.FindStringSubmatch(text)
	if match == nil {
		return nil
	}
	var files []string
	for _, line := range config.SplitLines(match[1]) {
		key, value, found := strings.Cut(strings.TrimFunc(line, config.Space), ":")
		if !found || strings.TrimFunc(key, config.Space) != "files" {
			continue
		}
		value, _, _ = strings.Cut(value, "#")
		for _, part := range strings.Split(value, ",") {
			if part = strings.TrimFunc(part, config.Space); part != "" {
				files = append(files, part)
			}
		}
	}
	return files
}

// SavedFiles is Files of a saved task as orch.changed_files reads it: none for a file that cannot
// be read or whose front matter Python refuses.
func SavedFiles(path string) []string {
	data, err := os.ReadFile(path)
	if err != nil || !utf8.Valid(data) {
		return nil
	}
	text := Text(data)
	if _, _, err := frontMatter(path, text); err != nil {
		return nil
	}
	return Files(text)
}

var (
	goalSection = regexp.MustCompile(strings.ReplaceAll(`(?ims)^##\s+Goal\s*$(.*?)(?:^##\s|\z)`, `\s`, config.SpaceClass))
	goalPoint   = regexp.MustCompile(`(?m)^[ \t]*\p{Nd}+[.)][ \t]+[^` + config.SpaceClass[1:])
)

// Size is a task body's words outside its checks block and its numbered goal points, Python's
// task_words and task_points.
func Size(body string) (words, points int) {
	if section := doneWhen.FindStringSubmatch(body); section != nil {
		if block := fence.FindString(section[1]); block != "" {
			body = strings.Replace(body, block, "", 1)
		}
	}
	if section := goalSection.FindStringSubmatch(body); section != nil {
		points = len(goalPoint.FindAllString(section[1], -1))
	}
	return len(strings.FieldsFunc(body, config.Space)), points
}
