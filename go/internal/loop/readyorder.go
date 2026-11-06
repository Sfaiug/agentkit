package loop

import (
	"agentkit/internal/pick"
	"agentkit/internal/usage"
)

// ReadyOrder is the order a pick draws the rules' executors, or with review their reviewers, in
// now, Python's staffing.ready_order: each whose harness cannot run a turn here left out before
// any budget rule reads the list.  The error is usage.Read's, usage.ErrPython before anything is
// written where the meters are not Go's to read.
func ReadyOrder(rules *pick.Rules, review bool) ([]string, error) {
	readings, err := usage.Read()
	if err != nil {
		return nil, err
	}
	return rules.Order(ready{readings, unable()}, review, nil), nil
}
