package launch

import "agentkit/internal/plan"

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
