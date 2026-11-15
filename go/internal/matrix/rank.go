package matrix

import (
	"agentkit/internal/config"
	"agentkit/internal/pick"
	"agentkit/internal/quality"
)

func init() { pick.Lineup = ranking }

// ranking is what a pick reads of the lineup last stored (Stored): its rank, Python's matrix.rank,
// and the models off in the model list (OffModels), false where that list cannot be read.  The
// rank is read off the answer the lineup gives with this config's prices and what ak's runs
// measured (Answer), never off the boards, as the pick ranks: after its usage read, as Python's
// rank prices a task then.  One it cannot give ranks no row, as Python's rank reads none where it
// cannot.  For a role each model takes its row at the effort it runs at there (RowOf), as the
// models handed the rank have it, and Ranks places them as the models screen does.
func ranking() (pick.Ranker, map[string]bool, bool) {
	off, err := OffModels()
	if err != nil {
		return nil, nil, false
	}
	return func(review bool, models map[string]config.Model, names []string) func(a, b string) int {
		role := "execute"
		if review {
			role = "review"
		}
		var rated []*quality.Rating
		if measured, err := Measured(); err == nil {
			if answer, err := Answer(Stored().Rows, nil, measured); err == nil {
				rated = answer[role].Rated
			}
		}
		rows := map[string]*quality.Rating{}
		for _, name := range names {
			rows[name] = RowOf(rated, models[name], models[name].TurnEffort(review))
		}
		return Ranks(role, names, rows)
	}, off, true
}
