package cli

import (
	"fmt"

	"agentkit/internal/quality"
	"agentkit/internal/run"
)

// drawn is a priced row of said, role's answer, as `ak models --json` draws it: its cost, board
// cost and how its cost was had, and what the screen notes beside it.
func drawn(row *quality.Rating, said *quality.Said, role string) *run.Object {
	entry := run.NewObject()
	entry.Set("release", row.Release)
	entry.Set("name", row.Name)
	entry.Set("effort", effortOf(row))
	entry.Set("quality", row.Quality)
	entry.Set("se", row.SE)
	board := row.Values.Get(quality.Costs[role])
	var cost any = *row.Cost
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
	return entry
}

// rowsDrawn is rows of said, each drawn.
func rowsDrawn(rows []*quality.Rating, said *quality.Said, role string) []any {
	out := []any{}
	for _, row := range rows {
		out = append(out, drawn(row, said, role))
	}
	return out
}

// othersDrawn is said's others, each drawn with why it is no choice and the name and effort of
// the row that says so, null for none.
func othersDrawn(said *quality.Said, role string) []any {
	others := []any{}
	for _, other := range said.Others {
		entry := drawn(other.Rating, said, role)
		entry.Set("why", other.Why)
		var by any
		if other.By != nil {
			named := run.NewObject()
			named.Set("name", other.By.Name)
			named.Set("effort", effortOf(other.By))
			by = named
		}
		entry.Set("by", by)
		others = append(others, entry)
	}
	return others
}

// effortOf is a row's effort as Python writes it, null where it names none.
func effortOf(row *quality.Rating) any {
	if row.Effort == "" {
		return nil
	}
	return row.Effort
}
