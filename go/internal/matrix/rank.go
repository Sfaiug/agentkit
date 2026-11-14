package matrix

import (
	"slices"

	"agentkit/internal/config"
	"agentkit/internal/history"
	"agentkit/internal/pick"
	"agentkit/internal/quality"
	"agentkit/internal/run"
)

func init() { pick.Lineup = ranking }

// ranking is what a pick reads of the lineup last stored (Stored): its rank, Python's matrix.rank,
// and the models off in the model list (OffModels).  The rank is read off the answer the lineup
// gives with this config's prices (Answer), never off the boards: for a role each model takes its
// row at the effort it runs at there (RowOf), as the models handed the rank have it, and Ranks
// places them as the models screen does.
//
// false where Go cannot give that answer as Python does.  Once a run of yours measured a row of
// the lineup, Python prices every role in one unit (matrix._costs, #2980), Answer each in its own;
// so a lineup a model runs a row of is Python's wherever history.db may hold a run
// (history.HoldsRun), measured or not, own's aside: the row of the run whose pick asks
// (pick.Launched) ends with its picks, and Python measures a run only once it ended.  Where it
// holds none, no run measured anything.
func ranking(own string) (pick.Ranker, map[string]bool, bool) {
	rows := Stored().Rows
	models, err := config.Models()
	if err != nil || ran(rows, models) && history.HoldsRun(own) {
		return nil, nil, false
	}
	off, err := OffModels()
	if err != nil {
		return nil, nil, false
	}
	answer, err := Answer(rows, nil, run.NewObject())
	if err != nil {
		return nil, nil, false
	}
	return func(review bool, models map[string]config.Model, names []string) func(a, b string) int {
		role := "execute"
		if review {
			role = "review"
		}
		rows := map[string]*quality.Rating{}
		for _, name := range names {
			rows[name] = RowOf(answer[role].Rated, models[name], models[name].TurnEffort(review))
		}
		return Ranks(role, names, rows)
	}, off, true
}

// ran is whether a model of models runs a row of rows, as the lineup holds it (`yours`).
func ran(rows []quality.Row, models map[string]config.Model) bool {
	for _, model := range models {
		if slices.ContainsFunc(rows, func(row quality.Row) bool {
			return slices.Contains(row.Runners, [2]string{model.Harness, model.ID})
		}) {
			return true
		}
	}
	return false
}
