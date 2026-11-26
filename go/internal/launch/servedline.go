package launch

import (
	"path/filepath"

	"agentkit/internal/plan"
)

func missingPlanLine(path string) string {
	return filepath.Base(path) + `: none of its ## Done when checks match an open plan line (your plan is what your bar counts): first run ak plan add "<outcome>" --check '<focused-check>' and put that same check in ## Done when`
}

// servedLine is what a launch's receipt names as the plan line its task serves, as Python's
// capture_launch names it: a seat's open line its checks match (plan.ServedLine), nil for none
// and outside a seat.  It is read before the slots lock, as Python reads it, and
// ErrPython, before anything is written, where the seat's plan cannot be read now.
func servedLine(seat string, checks []string) (any, error) {
	if seat == "" {
		return nil, nil
	}
	line, err := plan.ServedLine(seat, checks)
	switch {
	case err != nil:
		return nil, ErrPython
	case line == "":
		return nil, nil
	}
	return line, nil
}
