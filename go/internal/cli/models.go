package cli

import (
	"fmt"
	"io"
	"os"
	"strings"

	"agentkit/internal/config"
	"agentkit/internal/matrix"
	"agentkit/internal/menu"
	"agentkit/internal/quality"
	"agentkit/internal/run"
	"agentkit/internal/seat"
	"agentkit/internal/terminal"
)

func init() { commands["models"] = modelsAnswer }

// modelsAnswer answers `ak models` as Python's matrix.main does: the boards, the lineup, each role's
// answer, priced at what ak's own runs measured, and ak's own run numbers, as JSON with --json
// beside those measurements, else the models screen's role lines for the seat AGENTKIT_SESSION
// names where its record reads, else for new seats.  A home whose own numbers count a run
// (ownNumbers), or whose seat's record Go cannot read, is left to Python before anything is
// written.
func modelsAnswer(args []string, out, errOut io.Writer) int {
	fail := func(err error) int {
		fmt.Fprintf(errOut, "ak models: %s\n", err)
		return 1
	}
	c, err := matrix.Configured()
	if err != nil {
		return fail(err)
	}
	if ownNumbers(c.Names, c.Models) {
		return notImplemented(errOut, "models")
	}
	asJSON := contains(args, "--json")
	if session := os.Getenv("AGENTKIT_SESSION"); session != "" && !asJSON {
		selected, err := seat.ConfigSelection(session)
		if err != nil && !os.IsNotExist(err) {
			return notImplemented(errOut, "models")
		}
		if selected != nil {
			c.Selected = selected
		}
	}
	found, err := matrix.Refresh(contains(args, "--refresh"))
	if err != nil {
		return fail(err)
	}
	marked, ours, err := matrix.Compared(found.Rows)
	if err != nil {
		return fail(err)
	}
	measured, err := matrix.Measured()
	if err != nil {
		return fail(err)
	}
	answer, err := matrix.Answer(found.Rows, marked, measured)
	if err != nil {
		return fail(err)
	}
	if asJSON {
		whole := modelsJSON(answer, c.Names)
		whole.Set("task_usage", measured.Shares)
		fmt.Fprintln(out, run.Encode(whole))
		return 0
	}
	screen := terminal.For(out)
	lines := menu.ModelsLines(screen, menu.ModelsView{Answer: answer, Uses: c.Uses(answer), Models: c.Models,
		Compared: marked, Total: ours, Fetched: found.Fetched})
	if len(c.Names) > 0 {
		var own [][]string
		for _, name := range c.Names {
			// ownNumbers counts no run of it: its row is its name alone, as every screen says it
			own = append(own, []string{config.ModelName(name, c.Models), "-", "-", "-"})
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
