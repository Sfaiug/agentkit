package contract

import (
	"agentkit/internal/config"
	"agentkit/internal/matrix"
	"agentkit/internal/quality"
)

// switchedOff is whether the model list may turn a check model off: `models_off` names a release,
// or a release the lineup lists is not on, by `companies` or the makers your defaults run.  A
// contract turn runs the `[check]` model under the harness's name and Go judges the config's
// model of that name (worker.Refused), where Python judges the check model itself; with nothing
// off, neither refuses.
func switchedOff() bool {
	_, off, err := config.ModelList()
	if err != nil || len(off) > 0 {
		return true
	}
	rows := matrix.Stored().Rows
	on, _, err := matrix.Compared(rows)
	for _, role := range quality.Roles {
		for _, row := range quality.Rated(rows, role) {
			if err != nil || !on[row.Release] {
				return true
			}
		}
	}
	return false
}
