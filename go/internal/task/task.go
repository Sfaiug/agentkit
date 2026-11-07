// Package task reads the files a task is written in as Python ak does, and says what a task
// file may say: the task's front matter and done-when commands, and the front matter of a
// repository's AGENTS.md.
package task

import (
	"bytes"
	"context"
	"fmt"
	"math/big"
	"os"
	"os/exec"
	"regexp"
	"slices"
	"strings"
	"time"

	"agentkit/internal/commandhelp"
	"agentkit/internal/config"
)

var (
	// \s as Python reads it, Unicode's whitespace included
	doneWhen = regexp.MustCompile(strings.ReplaceAll(`(?ims)^##\s+Done when\s*$(.*?)(?:^##\s|\z)`, `\s`, config.SpaceClass))
	fence    = regexp.MustCompile("(?s)```(?:bash|sh)?\n(.*?)```")
	frontRe  = regexp.MustCompile(`(?s)^---\n(.*?)\n---\n?(.*)$`)
	agentsRe = regexp.MustCompile(`(?s)^---\n(|.*?\n)---`)
	onceRe   = regexp.MustCompile(strings.ReplaceAll(`^#\s*once\s*$`, `\s`, config.SpaceClass))
	// bash's own warning for a heredoc it never closes, from 3.2 (`bash: warning: …`) to 5.2
	// (`bash: line 1: warning: …`)
	unclosedHeredoc = regexp.MustCompile(`(?m)^[^:\n]+: (?:line \d+: )?warning: here-document at line \d+ delimited by end-of-file`)
)

var taskKeys = []string{"after", "base", "done_when_minutes", "files", "from", "merge", "repo",
	"rounds", "stall_minutes", "target", "turn_hours"}

// Read is a task's front matter, each key as it last says it, and its done-when commands, or
// the sentence ak refuses the file with: a key it does not read, a line that is no
// `key: value`, front matter left open, `## Decided` lines it cannot launch with (Decided), or
// no command in a bash block under `## Done when`.
func Read(path string) (map[string]string, []string, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return nil, nil, err
	}
	return Parse(path, Text(data))
}

// Parse is Read of the task at path as text says it, written there or not yet.
func Parse(path, text string) (map[string]string, []string, error) {
	meta, body, err := frontMatter(path, text)
	if err != nil {
		return nil, nil, err
	}
	if _, err := Decided(body); err != nil {
		return nil, nil, err
	}
	section := doneWhen.FindStringSubmatch(body)
	if section == nil {
		return nil, nil, fmt.Errorf("%s: no `## Done when` section", path)
	}
	block := fence.FindStringSubmatch(section[1])
	if block == nil {
		return nil, nil, fmt.Errorf("%s: `## Done when` has no ```bash fenced command block", path)
	}
	var cmds []string
	for _, line := range config.SplitLines(block[1]) {
		if line = strings.TrimFunc(line, config.Space); line != "" && !strings.HasPrefix(line, "#") {
			cmds = append(cmds, line)
		}
	}
	if len(cmds) == 0 {
		return nil, nil, fmt.Errorf("%s: `## Done when` block is empty; done means commands that exit 0", path)
	}
	return meta, cmds, nil
}

// frontMatter is a task's front matter, each key as it last says it, and the text after it, or
// the sentence ak refuses the file with, as Python's front_matter reads them.
func frontMatter(path, text string) (map[string]string, string, error) {
	meta, body := map[string]string{}, text
	if match := frontRe.FindStringSubmatch(text); match != nil {
		for _, line := range config.SplitLines(match[1]) {
			line = strings.TrimFunc(line, config.Space)
			if line == "" || strings.HasPrefix(line, "#") {
				continue
			}
			key, value, found := strings.Cut(line, ":")
			if !found {
				return nil, "", fmt.Errorf("%s: front matter line is not `key: value`: %s", path, commandhelp.Quote(line))
			}
			key = strings.TrimFunc(key, config.Space)
			if !slices.Contains(taskKeys, key) {
				return nil, "", fmt.Errorf("%s: unknown front-matter key %s; accepted keys: %s", path, commandhelp.Quote(key), strings.Join(taskKeys, ", "))
			}
			value, _, _ = strings.Cut(value, "#")
			meta[key] = strings.TrimFunc(value, config.Space)
		}
		body = match[2]
	} else if strings.HasPrefix(text, "---\n") {
		return nil, "", fmt.Errorf("%s: front matter needs a closing --- line", path)
	}
	return meta, body, nil
}

// Title is the task's first `# ` heading after its front matter, as Python's parse_task reads
// it, else stem.
func Title(text, stem string) string {
	if match := frontRe.FindStringSubmatch(text); match != nil {
		text = match[2]
	}
	for _, line := range config.SplitLines(text) {
		if heading, found := strings.CutPrefix(line, "# "); found {
			return strings.TrimFunc(heading, config.Space)
		}
	}
	return stem
}

// Refusal is the sentence a task read whole cannot start with, or "". A heredoc never works
// in done-when: each line runs as a command of its own, so the opening line reads an empty
// script and its body lines run as commands.
func Refusal(meta map[string]string, cmds []string) string {
	if _, ok := meta["after"]; ok {
		return "`after:` is gone: tasks launched together are independent pieces; build work that waits on another piece in your session, in order"
	}
	for _, cmd := range cmds {
		if opensHeredoc(cmd) {
			return fmt.Sprintf("done-when line %s opens a heredoc, but each line runs as a command of its own: put the script in a file the change adds, or on one line", commandhelp.Quote(cmd))
		}
	}
	return ""
}

// ChecksRefusal is the sentence for more than 3 checks a round runs, or "": every as the loop
// settles it, a `# once` line among them where the run has no landing.
func ChecksRefusal(every []string) string {
	if len(every) <= 3 {
		return ""
	}
	return fmt.Sprintf("%d done-when checks: a task has at most 3, one behaviour a reviewer holds in one read; split it", len(every))
}

// RoundsOver is the sentence for a round budget over the one in force, or "": it is never a default
// to raise. A value that is no number is left to the check that says so.
func RoundsOver(value, what string, budget int) string {
	rounds := config.Int(value)
	if rounds == nil || rounds.Cmp(big.NewInt(int64(budget))) <= 0 {
		return ""
	}
	return fmt.Sprintf("%s %s is over the budget: %d rounds, then a run goes back to its orchestrator to split or re-scope", what, rounds, budget)
}

// opensHeredoc is whether bash's own parser, reading the command as a whole script, meets a
// heredoc it never closes. `bash -n` runs nothing, so a shift, a comment, any quoting and a
// `<<<` here-string are no heredoc, exactly as when the line runs.
func opensHeredoc(command string) bool {
	if !strings.Contains(command, "<<") {
		return false
	}
	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()
	bash := exec.CommandContext(ctx, "bash", "-n", "-c", command)
	// nothing inherited may make bash read a file first or echo the line back (`verbose`)
	for _, entry := range os.Environ() {
		name, _, _ := strings.Cut(entry, "=")
		if !slices.Contains([]string{"BASH_ENV", "ENV", "SHELLOPTS", "BASHOPTS"}, name) {
			bash.Env = append(bash.Env, entry)
		}
	}
	bash.Env = append(bash.Env, "LC_ALL=C")
	var said bytes.Buffer
	bash.Stderr = &said
	_ = bash.Run()
	return ctx.Err() == nil && unclosedHeredoc.Match(said.Bytes())
}

// SplitOnce is the command without its trailing `# once` marker, the marker's `#` outside any
// quotes, and whether it had one, as Python's split_once reads it.
func SplitOnce(cmd string) (string, bool) {
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
				return strings.TrimRightFunc(cmd[:i], config.Space), true
			}
		}
	}
	return cmd, false
}

// FrontValue is a key's value in AGENTS.md front matter, or "" (FrontDeclared).
func FrontValue(text, key string) string {
	value, _ := FrontDeclared(text, key)
	return value
}

// Text is text as Python reads a text file or a command's output: every line ending a
// newline.
func Text(data []byte) string {
	return strings.NewReplacer("\r\n", "\n", "\r", "\n").Replace(string(data))
}
