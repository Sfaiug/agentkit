package cli

import (
	"bytes"
	"context"
	"errors"
	"fmt"
	"io"
	"os/exec"
	"strconv"
	"strings"
	"time"

	"agentkit/internal/config"
	"agentkit/internal/terminal"
	"agentkit/internal/tick"
)

// scoreboard is `--history`'s two weeks side by side, as an empty history gives them: every
// measure but ak's size reads from history.db, which `refused` leaves to Python while
// it exists.
func scoreboard(screen terminal.Screen, now time.Time) []string {
	return readScoreboard(now).render(screen)
}

// The tick receives the same report the history screen renders, keeping its measures here.
func auditScoreboard(out io.Writer) tick.AuditReport {
	return func(now time.Time) ([]string, string) {
		board := readScoreboard(now)
		return board.render(terminal.For(out)), board.loss()
	}
}

type measure struct {
	name  string
	value *int
}

// scoreBoard is an empty history's two weeks, with sizes read from the same Git snapshot.
type scoreBoard struct{ sizes [2][]measure }

func readScoreboard(now time.Time) scoreBoard {
	repo := config.Repo()
	size := func(ref string) []measure {
		if ref == "" {
			return nil
		}
		code := gitOutput(repo, "grep", "-I", "-h", "--no-color", "-e", "^", ref, "--",
			"agentkit/", "bin/", "hooks/", "adapters/", "tools/", "install.sh")
		readme, agents := gitOutput(repo, "show", ref+":README.md"), gitOutput(repo, "show", ref+":AGENTS.md")
		if code == nil && readme == nil && agents == nil {
			return nil
		}
		var parts []measure
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
				parts = append(parts, measure{part.name, nil})
			} else {
				count := part.count(part.value)
				parts = append(parts, measure{part.name, &count})
			}
		}
		return parts
	}
	before := ""
	if out := gitOutput(repo, "rev-list", "--first-parent", "-1",
		"--before="+now.Add(-7*24*time.Hour).UTC().Format("2006-01-02T15:04:05Z"), "HEAD"); out != nil {
		before = strings.TrimSpace(string(out))
	}
	return scoreBoard{[2][]measure{size("HEAD"), size(before)}}
}

func (board scoreBoard) render(screen terminal.Screen) []string {
	size := func(parts []measure) string {
		if parts == nil {
			return "size unavailable"
		}
		var words []string
		for _, part := range parts {
			word := part.name + " unknown"
			if part.value != nil {
				word = fmt.Sprintf("%d %s", *part.value, part.name)
			}
			words = append(words, word)
		}
		return strings.Join(words, ", ")
	}
	rows := [][3]string{{"", "last 7 days", "7 days before"}}
	for _, measure := range [][2]string{{"products", "no runs ended"}, {"ak", "no runs ended"},
		{"tokens", "no tokens recorded"}, {"intent", "not recorded"}, {"owner", "not recorded"},
		{"built", "no runs ended"}, {"waits", "not recorded"}, {"merged", "no merged change"},
		{"parks", "not recorded"}, {"sunk", "no tokens recorded"}, {"broke", "no merged change"}} {
		rows = append(rows, [3]string{measure[0], measure[1], measure[1]})
	}
	rows = append(rows, [3]string{"ak size", size(board.sizes[0]), size(board.sizes[1])})
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

// loss follows the vision's order. Without history only size has a reading.
func (board scoreBoard) loss() string {
	first := "no loss to name, since no run ended in two weeks"
	number := func(value int) string {
		text := strconv.Itoa(value)
		for at := len(text) - 3; at > 0; at -= 3 {
			text = text[:at] + "," + text[at:]
		}
		return text
	}
	for i, part := range board.sizes[0] {
		if part.value == nil {
			continue
		}
		var previous *int
		if len(board.sizes[1]) > i {
			previous = board.sizes[1][i].value
		}
		before := "not recorded"
		if previous != nil {
			before = number(*previous)
		}
		words := "the largest loss is ak's " + part.name + ", " + number(*part.value) + " against " + before + " the week before"
		if first == "no loss to name, since no run ended in two weeks" {
			first = words
		}
		if previous != nil && *part.value > *previous {
			return words
		}
	}
	return first
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
