package cli

import (
	"cmp"
	"fmt"
	"slices"

	"agentkit/internal/config"
	"agentkit/internal/matrix"
	"agentkit/internal/pick"
)

// opensOn is the models a new seat may open on, none off in the model list (matrix.OffModels):
// the one asked for, else every one offered, which the question may pick.  Refused in Python's
// words where none may, as orch.choose refuses with every model off, asked for one or not, and
// orch.command one asked for that is off (matrix.Refused).
func opensOn(asked string) ([]string, error) {
	offered, err := config.Offered()
	off, unread := matrix.OffModels()
	if err = cmp.Or(err, unread); err != nil {
		return nil, err
	}
	on := slices.DeleteFunc(offered, func(name string) bool { return off[name] })
	switch {
	case len(on) == 0:
		return nil, fmt.Errorf("every model is %s: turn one on with `companies` or `models_off` in config.toml", pick.OffList)
	case asked != "":
		return []string{asked}, matrix.Refused(asked)
	}
	return on, nil
}
