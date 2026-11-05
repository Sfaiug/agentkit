package tick

import (
	"agentkit/internal/notify"
	"agentkit/internal/seat"
)

func healthReady(live seat.Live) bool {
	return live.Stall == nil && quietLogin(live) && live.Bound && titleKept(live) &&
		(notify.Last(live.Name) == nil || unansweredQuestion(live))
}

func accountTurns() error {
	carried, err := seat.AccountTurns()
	if !carried {
		return errLeft
	}
	return err
}
