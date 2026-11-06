package cli

import (
	"agentkit/internal/config"
	"agentkit/internal/matrix"
	"agentkit/internal/seat"
)

// stepNewSeatsEffort is a fresh window's effort step, onto `word`, saved as seat.SaveNewSeatsEffort
// saves it, the row's other shown efforts staying where they stand, as Python's config_effort
// holds them.  What to say under the matrix, or ""; false, with nothing written, leaves the step
// to Python.
func stepNewSeatsEffort(c *matrix.Configuration, name string, column int, word string) (string, bool) {
	var hold []string
	for _, shown := range c.Columns(name) {
		if shown >= 3 && shown != column {
			hold = append(hold, config.RoleEfforts[shown-3])
		}
	}
	step := config.EffortStep{Model: name, Key: config.RoleEfforts[column-3], Effort: word, Hold: hold}
	carried, err := seat.SaveNewSeatsEffort(step)
	if !carried {
		return "", false
	}
	if err != nil {
		return "config: " + err.Error(), true
	}
	model := c.Models[name]
	model.Efforts = step.Apply(model.Efforts)
	c.Models[name] = model
	return "", true
}
