package cli

import (
	"slices"
	"time"

	"agentkit/internal/config"
	"agentkit/internal/history"
	"agentkit/internal/run"
)

// ownNumbers is whether ak's own numbers, which Go does not count yet, count a run of an offered
// model, as Python's matrix.live reads the history: a real run that ended with a verdict of the
// work it executed or whose pull request its seat wrote, or a run it finished a review of.
func ownNumbers(names []string, models map[string]config.Model) bool {
	db := history.Look()
	defer db.Close()
	ended, _ := db.EndedRuns(0, float64(time.Now().UnixNano())/1e9)
	for _, row := range ended {
		if slices.Contains(run.Judged, row.Text("final_state")) &&
			(slices.Contains(names, row.Text("executor")) || slices.Contains(names, row.Text("own_orchestrator"))) {
			return true
		}
	}
	for _, name := range names {
		if reviewed, _ := db.ReviewedRuns(models[name].Harness, models[name].ID); len(reviewed) > 0 {
			return true
		}
	}
	return false
}
