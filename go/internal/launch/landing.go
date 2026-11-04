package launch

import (
	"errors"
	"os"
	"path/filepath"
	"regexp"
	"strings"

	"agentkit/internal/run"
	"agentkit/internal/task"
)

// going leaves active work to Python's rival check, except a green delivery provably distinct
// from this task. An empty path keeps the conservative check used by seat admission.
func going(path string) bool {
	for _, dir := range run.Dirs() {
		record, err := run.Read(dir)
		if errors.Is(err, run.ErrLoneSurrogate) {
			return true
		}
		if record != nil && run.Active(record) &&
			!(path != "" && run.InLine(record) && run.ProcessActive(record) && distinctLanding(path, dir, record)) {
			return true
		}
	}
	return false
}

var titleWords = regexp.MustCompile(`[a-z0-9]+`)

// distinctLanding proves the no-rival case of Python's already_under_way: no shared named
// test and fewer than four shared title words. Ambiguous overlaps stay Python's to judge.
func distinctLanding(path, dir string, record *run.Object) bool {
	data, err := os.ReadFile(path)
	if err != nil || record.Str("title") == "" || record.Truthy("review_pr") || record.Truthy("repair") {
		return false
	}
	_, checks, err := task.Read(path)
	if err != nil {
		return false
	}
	_, other, err := task.Read(filepath.Join(dir, "task.md"))
	if err != nil {
		return false
	}
	tests := func(commands []string) map[string]bool {
		found := map[string]bool{}
		for _, command := range commands {
			for _, token := range strings.Fields(command) {
				name := strings.Trim(token, "\"'")
				stem := filepath.Base(name)
				base := strings.TrimSuffix(stem, filepath.Ext(stem))
				if !strings.ContainsAny(name, "*?[") && (strings.HasPrefix(stem, "test_") || strings.HasSuffix(base, "_test")) {
					found[name] = true
				}
			}
		}
		return found
	}
	theirs := tests(other)
	for name := range tests(checks) {
		if theirs[name] {
			return false
		}
	}
	words := map[string]bool{}
	for _, word := range titleWords.FindAllString(strings.ToLower(record.Str("title")), -1) {
		words[word] = true
	}
	shared := map[string]bool{}
	for _, word := range titleWords.FindAllString(strings.ToLower(task.Title(task.Text(data), filepath.Base(path))), -1) {
		if words[word] {
			shared[word] = true
		}
	}
	return len(shared) < 4
}
