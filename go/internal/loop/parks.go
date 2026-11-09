package loop

import (
	"agentkit/internal/pick"
	"agentkit/internal/usage"
)

// Parks is whether a run on these rules, its --exec named or "", ends at its pick before any turn,
// as pick ends it: nobody of it can run here, or the meters leave it no pair.
func Parks(rules *pick.Rules, named string) bool {
	cannot := unable()
	if cannot[named] != "" || rules.Unstaffed(cannot) != "" {
		return true
	}
	readings, err := usage.Read()
	if err != nil {
		return false
	}
	room := ready{readings, cannot}
	if named != "" {
		_, ok := rules.PairFor(room, named)
		return !ok
	}
	_, _, ok := rules.Pair(room)
	return !ok
}
