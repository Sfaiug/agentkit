package cli

import (
	"agentkit/internal/config"
	"agentkit/internal/matrix"
	"agentkit/internal/seat"
)

// stepNewSeatsEffort is a fresh window's effort step, onto `word`: saved to the entry new seats
// open at, every seat's record first holding the efforts it runs at (seat.KeepConfigEfforts), so
// none moves with it, and the row's other shown efforts staying where they stand, as Python's
// config_effort holds them.  What to say under the matrix, or ""; false, before anything is
// written, leaves a step whose records Go does not keep (seat.KeepsConfigEfforts) to Python.
func stepNewSeatsEffort(c *matrix.Configuration, name string, column int, word string) (string, bool) {
	if !seat.KeepsConfigEfforts() {
		return "", false
	}
	var hold []string
	for _, shown := range c.Columns(name) {
		if shown >= 3 && shown != column {
			hold = append(hold, config.RoleEfforts[shown-3])
		}
	}
	step := config.EffortStep{Model: name, Key: config.RoleEfforts[column-3], Effort: word, Hold: hold}
	if err := config.StepEffort(step, seat.KeepConfigEfforts); err != nil {
		return "config: " + err.Error(), true
	}
	model := c.Models[name]
	model.Efforts = step.Apply(model.Efforts)
	c.Models[name] = model
	return "", true
}
