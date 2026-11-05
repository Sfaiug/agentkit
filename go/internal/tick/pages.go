package tick

import (
	"cmp"
	"io"
	"time"

	"agentkit/internal/notify"
	"agentkit/internal/plan"
	"agentkit/internal/seat"
)

// cards is the card transitions row (notify.tick_cards): each seat's card follows the word the
// health row published, read under the card's lock and never off the screen again. A transition
// Go does not carry leaves the rest of the tick to Python at that seat.
func cards(errOut io.Writer) error {
	names, known := seat.Seats(time.Now())
	if !known {
		return errLeft
	}
	for _, name := range names {
		carried, err := notify.TurnedQuestion(name, seat.Published, errOut)
		if !carried && err == nil {
			carried, err = notify.TurnedNeed(name, seat.Published, errOut)
		}
		if !carried && err == nil {
			carried, err = notify.TurnedPlan(name, seat.Published, plan.Outcomes)
		}
		if !carried && err == nil {
			carried, err = notify.TurnedRetiredQuestion(name, seat.Published)
		}
		if err != nil || !carried {
			return cmp.Or(err, errLeft)
		}
	}
	return nil
}
