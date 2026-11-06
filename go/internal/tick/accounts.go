package tick

import (
	"agentkit/internal/notify"
	"agentkit/internal/seat"
)

func healthReady(live seat.Live) bool { return live.Stall == nil && looked(live) }

// looked is whether the health row does no more before it reads the seat's account than look:
// no login to ask after, its pane named, its title its own, and no notice to answer by its output.
func looked(live seat.Live) bool {
	return quietLogin(live) && live.Bound && titleKept(live) && (notify.Last(live.Name) == nil || unansweredQuestion(live))
}

func accountTurns() error {
	carried, err := seat.AccountTurns()
	if !carried {
		return errLeft
	}
	return err
}
