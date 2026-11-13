package matrix

import (
	"cmp"
	"slices"

	"agentkit/internal/config"
	"agentkit/internal/quality"
)

// A Use is what one role of a seat, or of new seats, runs: Model its model's name, "" for none;
// Effort the effort it runs it at there; Row its row, nil where none is.
type Use struct {
	Model, Effort string
	Row           *quality.Rating
}

// Uses is what each role of c's selection uses off answer, as Python's matrix.uses: its
// orchestrator, named even once the config drops it, else its first mark as Rank orders them; the
// effort the selection runs it at; and its row (RowOf).
func (c *Configuration) Uses(answer map[string]*quality.Said) map[string]Use {
	workers := c.Selected.List("workers")
	marks := [][]any{{c.Selected.Get("orchestrator")}, workers, workers}
	if c.Selected.Has("reviewers") {
		marks[2] = c.Selected.List("reviewers")
	}
	used := map[string]Use{}
	for at, role := range quality.Roles {
		var known []string
		rows := map[string]*quality.Rating{}
		for _, mark := range marks[at] {
			name, _ := mark.(string)
			if model, ok := c.Models[name]; ok {
				known = append(known, name)
				rows[name] = RowOf(answer[role].Rated, model, c.Effort(name, at))
			}
		}
		var use Use
		if ranked := Rank(role, known, rows); len(ranked) > 0 {
			use = Use{ranked[0], c.Effort(ranked[0], at), rows[ranked[0]]}
		} else if len(marks[at]) > 0 {
			use.Model, _ = marks[at][0].(string)
		}
		used[role] = use
	}
	return used
}

// Rank is names, configured models, in the order Python's matrix.rank places them for role off
// each one's row (rows, as RowOf finds it): the role's pick among these rows first, then the rest
// by quality, then a model no row is; an equal place keeps names' order.
func Rank(role string, names []string, rows map[string]*quality.Rating) []string {
	var found []*quality.Rating
	for _, name := range names {
		if rows[name] != nil {
			found = append(found, rows[name])
		}
	}
	pick := quality.Pick(found, role)
	place := func(name string) (int, float64) {
		switch row := rows[name]; row {
		case nil:
			return 2, 0
		case pick:
			return 0, -row.Quality
		default:
			return 1, -row.Quality
		}
	}
	ranked := slices.Clone(names)
	slices.SortStableFunc(ranked, func(a, b string) int {
		first, better := place(a)
		second, worse := place(b)
		return cmp.Or(cmp.Compare(first, second), cmp.Compare(better, worse))
	})
	return ranked
}

// RowOf is the row of rated the model runs at effort, as the lineup holds it (Python's
// matrix.row_of): at that effort, else at none, the model however it is run, else, run at `none`,
// its one row; nil where none is.
func RowOf(rated []*quality.Rating, model config.Model, effort string) *quality.Rating {
	var held []*quality.Rating
	for _, row := range rated {
		if slices.Contains(row.Runners, [2]string{model.Harness, model.ID}) {
			held = append(held, row)
		}
	}
	for _, want := range []string{effort, ""} {
		if at := slices.IndexFunc(held, func(row *quality.Rating) bool { return row.Effort == want }); at >= 0 {
			return held[at]
		}
	}
	if effort == "none" && len(held) == 1 {
		return held[0]
	}
	return nil
}
