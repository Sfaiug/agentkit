package cli

import (
	"bytes"
	"context"
	"errors"
	"fmt"
	"os/exec"
	"strings"
	"time"

	"agentkit/internal/config"
	"agentkit/internal/terminal"
)

// scoreboard is `--history`'s two weeks side by side, as an empty history gives them: every
// measure but ak's size reads from history.db, which `refused` leaves to Python while
// it exists.
func scoreboard(screen terminal.Screen, now time.Time) []string {
	repo := config.Repo()
	size := func(ref string) string {
		if ref == "" {
			return "size unavailable"
		}
		code := gitOutput(repo, "grep", "-I", "-h", "--no-color", "-e", "^", ref, "--",
			"agentkit/", "bin/", "hooks/", "adapters/", "tools/", "install.sh")
		readme, agents := gitOutput(repo, "show", ref+":README.md"), gitOutput(repo, "show", ref+":AGENTS.md")
		if code == nil && readme == nil && agents == nil {
			return "size unavailable"
		}
		var parts []string
		for _, part := range []struct {
			value []byte
			name  string
			count func([]byte) int
		}{
			{code, "code lines", func(text []byte) int { return bytes.Count(text, []byte("\n")) }},
			{readme, "README words", wordCount},
			{agents, "AGENTS.md words", wordCount},
		} {
			if part.value == nil {
				parts = append(parts, part.name+" unknown")
			} else {
				parts = append(parts, fmt.Sprintf("%d %s", part.count(part.value), part.name))
			}
		}
		return strings.Join(parts, ", ")
	}
	before := ""
	if out := gitOutput(repo, "rev-list", "--first-parent", "-1",
		"--before="+now.Add(-7*24*time.Hour).UTC().Format("2006-01-02T15:04:05Z"), "HEAD"); out != nil {
		before = strings.TrimSpace(string(out))
	}
	rows := [][3]string{{"", "last 7 days", "7 days before"}}
	for _, measure := range [][2]string{{"products", "no runs ended"}, {"ak", "no runs ended"},
		{"tokens", "no tokens recorded"}, {"intent", "not recorded"}, {"owner", "not recorded"},
		{"built", "no runs ended"}, {"waits", "not recorded"}, {"merged", "no merged change"},
		{"parks", "not recorded"}, {"sunk", "no tokens recorded"}, {"broke", "no merged change"}} {
		rows = append(rows, [3]string{measure[0], measure[1], measure[1]})
	}
	rows = append(rows, [3]string{"ak size", size("HEAD"), size(before)})
	width := screen.ContentWidth()
	room := max(1, (width-12)/2)
	lines := terminal.Wrap("Scoreboard (reported tokens; size now and 7 days ago)", width)
	for _, row := range rows {
		left, right := terminal.Wrap(row[1], room), terminal.Wrap(row[2], room)
		for i := range max(len(left), len(right)) {
			cells := []string{"", at(left, i), at(right, i)}
			if i == 0 {
				cells[0] = row[0]
			}
			lines = append(lines, screen.TableRow(cells, []int{8, room, room}, nil))
		}
	}
	return lines
}

func at(lines []string, i int) string {
	if i < len(lines) {
		return lines[i]
	}
	return ""
}

func wordCount(text []byte) int {
	return len(strings.FieldsFunc(strings.ToValidUTF8(string(text), "�"), config.Space))
}

// gitOutput is git's stdout in that repository, or nil where it cannot answer in ten
// seconds; `git grep` finding nothing is an answer.
func gitOutput(repo string, args ...string) []byte {
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	out, err := exec.CommandContext(ctx, "git", append([]string{"-C", repo}, args...)...).Output()
	var exit *exec.ExitError
	if err == nil || args[0] == "grep" && errors.As(err, &exit) && exit.ExitCode() == 1 {
		return out
	}
	return nil
}
