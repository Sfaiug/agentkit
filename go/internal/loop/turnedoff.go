package loop

import (
	"agentkit/internal/matrix"
	"agentkit/internal/pick"
)

// turnedOff is why each model off in the model list cannot run a turn here, whatever its harness
// says, as Python's usage.unready reads it first: so a dry tick, which asks no harness, still
// leaves out a saved model that is off.
func turnedOff() map[string]string {
	found := map[string]string{}
	off, _ := matrix.OffModels() // a list that cannot be read hands the pick over (pick.Within)
	for name, isOff := range off {
		if isOff {
			found[name] = pick.OffList
		}
	}
	return found
}
