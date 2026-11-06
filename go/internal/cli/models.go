package cli

import (
	"errors"
	"fmt"
	"io"
	"io/fs"
	"os"
	"path/filepath"
	"strings"

	"agentkit/internal/config"
	"agentkit/internal/matrix"
	"agentkit/internal/menu"
	"agentkit/internal/quality"
	"agentkit/internal/run"
	"agentkit/internal/terminal"
	"agentkit/internal/usage"
)

func init() { commands["models"] = modelsAnswer }

// modelsAnswer answers `ak models` as Python's matrix.main does: the boards, the lineup, each role's
// answer and ak's own run numbers, as JSON with --json beside what a million tokens of each model
// cost of its week and a run of it in each role, else drawn.  Its own numbers are the one part
// that reads SQLite: a home with a history.db is left to Python before anything is asked.
func modelsAnswer(args []string, out, errOut io.Writer) int {
	if _, err := os.Stat(filepath.Join(config.Home(), "history.db")); !errors.Is(err, fs.ErrNotExist) {
		return notImplemented(errOut, "models")
	}
	fail := func(err error) int {
		fmt.Fprintf(errOut, "ak models: %s\n", err)
		return 1
	}
	found, err := matrix.Refresh(contains(args, "--refresh"))
	if errors.Is(err, matrix.ErrPriced) {
		return notImplemented(errOut, "models")
	}
	if err != nil {
		return fail(err)
	}
	marked, err := matrix.Compared(found.Rows)
	if err != nil {
		return fail(err)
	}
	names, err := config.Offered()
	if err != nil {
		return fail(err)
	}
	answer := quality.Answer(found.Rows, marked)
	if contains(args, "--json") {
		readings, err := usage.Cached()
		if err != nil {
			return fail(err)
		}
		rates, err := readings.Rates()
		if err != nil {
			return fail(err)
		}
		whole := modelsJSON(answer, names)
		whole.Set("usage", rates)
		whole.Set("task_usage", usage.TaskUsage(rates))
		fmt.Fprintln(out, run.Encode(whole))
		return 0
	}
	screen := terminal.For(out)
	current := map[string]bool{}
	for _, row := range found.Rows {
		current[row.Release] = true
	}
	lines := menu.ModelsBody(screen, menu.ModelsSaid(screen, answer, found.Rows), marked, len(current), found.Fetched)
	if len(names) > 0 {
		var own [][]string
		for _, name := range names {
			own = append(own, []string{name, "-", "-", "-"}) // a home without a history has run nothing
		}
		lines = append(append(lines, ""), menu.LiveLines(screen, own)...)
	}
	fmt.Fprintln(out, strings.Join(lines, "\n"))
	return 0
}

// modelsJSON is each role's best and front, with what the screen notes beside each row, and ak's
// own numbers, null for a model that ran nothing.
func modelsJSON(answer map[string]*quality.Said, names []string) *run.Object {
	whole := run.NewObject()
	for _, role := range quality.Roles {
		said := answer[role]
		front := []any{}
		for _, row := range said.Front {
			entry := run.NewObject()
			entry.Set("release", row.Release)
			entry.Set("name", row.Name)
			if row.Effort == "" {
				entry.Set("effort", nil)
			} else {
				entry.Set("effort", row.Effort)
			}
			entry.Set("quality", row.Quality)
			entry.Set("se", row.SE)
			entry.Set("cost", row.Values.Get(quality.Costs[role]))
			notes := []any{}
			if row == said.Pick {
				notes = append(notes, "pick")
			}
			if missing := row.Missing(); missing > 0 {
				notes = append(notes, fmt.Sprintf("%d missing", missing))
			}
			if !row.Yours {
				notes = append(notes, "no harness")
			}
			entry.Set("notes", notes)
			front = append(front, entry)
		}
		rolled := run.NewObject()
		if said.Best == nil {
			rolled.Set("best", nil)
		} else {
			rolled.Set("best", *said.Best)
		}
		rolled.Set("front", front)
		whole.Set(role, rolled)
	}
	live := run.NewObject()
	for _, name := range names {
		cells := run.NewObject()
		for _, role := range quality.Roles {
			cells.Set(role, nil)
		}
		live.Set(name, cells)
	}
	whole.Set("live", live)
	return whole
}
