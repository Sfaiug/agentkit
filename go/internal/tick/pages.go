package tick

import (
	"cmp"
	"io"
	"slices"
	"time"

	"agentkit/internal/notify"
	"agentkit/internal/plan"
	"agentkit/internal/seat"
)

// cards is the card transitions row (notify.tick_cards): each seat's card follows the word worked
// out afresh under the card's lock, as Python's transition climbs it, and the card of a seat
// nothing is left of goes. A transition Go does not carry leaves the rest of the tick to Python
// at that seat.
func cards(errOut io.Writer, log func(string)) error {
	names, known := seat.Seats(time.Now())
	if !known {
		return errLeft
	}
	for _, name := range names {
		carried, err := notify.TurnedQuestion(name, seat.CardWord, errOut)
		if !carried && err == nil {
			carried, err = notify.TurnedNeed(name, seat.CardAnswer, errOut)
		}
		if !carried && err == nil {
			carried, err = notify.TurnedGoneNeed(name, seat.CardWord, errOut)
		}
		if !carried && err == nil {
			carried, err = notify.TurnedPlan(name, seat.CardWord, plan.Outcomes)
		}
		if !carried && err == nil {
			carried, err = notify.TurnedRetiredQuestion(name, seat.CardWord)
		}
		if !carried && err == nil {
			carried, err = notify.TurnedKeptQuestion(name, seat.CardWord)
		}
		if err != nil || !carried {
			return cmp.Or(err, errLeft)
		}
	}
	for _, name := range recorded("card") {
		if !slices.Contains(names, name) && seat.Unheld(name) {
			notify.ForgetCard(name, log)
		}
	}
	return nil
}
