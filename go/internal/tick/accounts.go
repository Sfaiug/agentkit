package tick

import (
	"agentkit/internal/seat"
)

func healthReady(live seat.Live) bool { return live.Stall == nil && looked(live) }

// looked is whether the health row does no more before it reads the seat's account than look:
// no login to ask after, its pane named, its title its own, and no notice to answer by its output.
func looked(live seat.Live) bool {
	return quietLogin(live) && live.Bound && titleKept(live) && (standing(live.Name) == nil || questionRead(live))
}

// continueTurns is the rebooted and switched turns rows (watch.continue_turns), the latter's for
// moves to another account.
func continueTurns(accounts bool) func() error {
	return func() error {
		carried, err := seat.ContinueTurns(accounts)
		if !carried {
			return errLeft
		}
		return err
	}
}
