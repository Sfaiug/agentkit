package cli

import (
	"fmt"
	"io"
	"strings"

	"agentkit/internal/config"
	"agentkit/internal/matrix"
	"agentkit/internal/menu"
	"agentkit/internal/quality"
	"agentkit/internal/run"
	"agentkit/internal/terminal"
)

func init() { commands["models"] = modelsAnswer }

// modelsAnswer answers `ak models` as Python's matrix.main does: the boards, the lineup, each role's
// answer, priced at what ak's own runs measured, and ak's own run numbers, as JSON with --json
// beside those measurements, else drawn.  A home whose own numbers count a run (ownNumbers) is
// left to Python before anything is written.
func modelsAnswer(args []string, out, errOut io.Writer) int {
	fail := func(err error) int {
		fmt.Fprintf(errOut, "ak models: %s\n", err)
		return 1
	}
	names, err := config.Offered()
	if err != nil {
		return fail(err)
	}
	models, err := config.Models()
	if err != nil {
		return fail(err)
	}
	if ownNumbers(names, models) {
		return notImplemented(errOut, "models")
	}
	asJSON := contains(args, "--json")
	found, err := matrix.Refresh(contains(args, "--refresh"))
	if err != nil {
		return fail(err)
	}
	marked, ours, err := matrix.Compared(found.Rows)
	if err != nil {
		return fail(err)
	}
	shares, err := matrix.Shares()
	if err != nil {
		return fail(err)
	}
	answer, err := matrix.Answer(found.Rows, marked, shares)
	if err != nil {
		return fail(err)
	}
	if asJSON {
		whole := modelsJSON(answer, names)
		whole.Set("task_usage", shares)
		fmt.Fprintln(out, run.Encode(whole))
		return 0
	}
	screen := terminal.For(out)
	lines := menu.ModelsBody(screen, menu.ModelsSaid(screen, answer, found.Rows), marked, ours, found.Fetched)
	if len(names) > 0 {
		var own [][]string
		for _, name := range names {
			own = append(own, []string{name, "-", "-", "-"}) // ownNumbers counts no run of it
		}
		lines = append(append(lines, ""), menu.LiveLines(screen, own)...)
	}
	fmt.Fprintln(out, strings.Join(lines, "\n"))
	return 0
}

// modelsJSON is each role's best, cost unit and front, with each row's cost, board cost and how
// its cost was had, and what the screen notes beside each row; and ak's own numbers, null for a
// model that ran nothing.
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
			board := row.Values.Get(quality.Costs[role])
			var cost any = *row.Cost // a front row has one
			if row.CostRule == "board" {
				cost = board // as the board wrote it: an int stays one
			}
			entry.Set("cost", cost)
			entry.Set("board_cost", board)
			entry.Set("cost_rule", row.CostRule)
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
		rolled.Set("cost_unit", said.CostUnit)
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
