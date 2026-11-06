package cli

import (
	"strings"

	"agentkit/internal/usage"
)

// chosen is the orchestrator a new seat offers first and why, as Python's orch.choose and
// prompt_orchestrator read usage: the default while it has something left to spend, else the first
// offered model with a window left, then the first on credits, which cost money; with every one
// spent, the default all the same, warned.  suffix follows the question's bracket where the
// default was passed over, saying why without the pick's own reading.
func chosen(readings *usage.Readings, offered []string, fallback string) (name, reason, suffix string) {
	order := []string{fallback}
	for _, each := range offered {
		if each != fallback {
			order = append(order, each)
		}
	}
	var notes []string
	for _, each := range order {
		spent, why := readings.ModelSpent(each)
		said := strings.Join(append([]string{why}, notes...), "; ")
		if !spent && !readings.OnCredits(each) {
			name, reason = each, said
			break
		}
		if !spent && name == "" {
			name, reason = each, said
		}
		notes = append(notes, "skipped "+each+": "+why)
	}
	if name == "" {
		name, reason = fallback, "WARN "+strings.Join(notes, "; ")+"; every model is exhausted, launching "+fallback+" anyway"
	}
	if name != fallback || strings.HasPrefix(reason, "WARN") {
		_, own := readings.ModelSpent(name)
		suffix = " (" + strings.TrimPrefix(reason, own+"; ") + ")"
	}
	return name, reason, suffix
}
