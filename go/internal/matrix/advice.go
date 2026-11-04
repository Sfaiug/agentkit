package matrix

import (
	"slices"

	"agentkit/internal/config"
	"agentkit/internal/quality"
	"agentkit/internal/run"
)

func runners(row *run.Object) [][2]string {
	var found [][2]string
	for _, value := range row.List("yours") {
		if entry, ok := value.(*run.Object); ok {
			found = append(found, [2]string{entry.Str("harness"), entry.Str("model")})
		}
	}
	return found
}

// Takes matches each role's take to the first configured model running it, as menu.takes
// does in Python. The recommendation itself belongs only to quality.Answer.
func (c *Configuration) Takes(answer map[string]*quality.Said) []config.EffortStep {
	var steps []config.EffortStep
	for i, role := range quality.Roles {
		row := answer[role].Take
		if row == nil {
			continue
		}
		for _, name := range c.Names {
			entry := c.Models[name]
			if slices.Contains(row.Runners, [2]string{entry.Harness, entry.ID}) {
				steps = append(steps, config.EffortStep{Model: name, Key: config.RoleEfforts[i], Effort: row.Effort})
				break
			}
		}
	}
	return steps
}

// Stored is the last complete lineup while the boards are being read again.
func Stored() *Matrix {
	held := stored()
	fetched, _ := held.Num("fetched_at")
	return &Matrix{Rows: rowsOf(held.List("lineup")), Fetched: fetched}
}
