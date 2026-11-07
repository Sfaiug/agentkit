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

// modelsJSON is each role's best, cost unit, front, choices and others, each row drawn; and ak's
// own numbers, null for a model that ran nothing.
func modelsJSON(answer map[string]*quality.Said, names []string) *run.Object {
	whole := run.NewObject()
	for _, role := range quality.Roles {
		said := answer[role]
		rolled := run.NewObject()
		if said.Best == nil {
			rolled.Set("best", nil)
		} else {
			rolled.Set("best", *said.Best)
		}
		rolled.Set("cost_unit", said.CostUnit)
		rolled.Set("front", rowsDrawn(said.Front, said, role))
		rolled.Set("choices", rowsDrawn(said.Choices, said, role))
		rolled.Set("others", othersDrawn(said, role))
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
