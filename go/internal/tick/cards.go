package tick

import (
	"cmp"
	"io"
	"path/filepath"
	"slices"
	"strings"
	"time"

	"agentkit/internal/config"
	"agentkit/internal/notify"
	"agentkit/internal/plan"
	"agentkit/internal/seat"
)

// unasked is whether typed answers has nothing to do: nothing asked, or a recorded question
// with no newer message from the owner (notify.answer_typed).
func unasked(live seat.Live) bool {
	_, asked := notify.AskedAt(live.Name)
	return notify.Last(live.Name) == nil && !live.File.Truthy("unasked") && (!asked || notify.RetiredQuestion(live.Name)) || unansweredQuestion(live) || notify.UnansweredDialog(live.Name)
}

// cardsHeld is whether every card is a seat's, none left of a seat gone (notify.tick_cards).
func cardsHeld() bool {
	seats, known := seat.Seats(time.Now())
	return known && !slices.ContainsFunc(recorded("card"), func(name string) bool { return !slices.Contains(seats, name) })
}

// recorded is the seat each record of that kind is named for.
func recorded(kind string) (names []string) {
	for _, path := range config.SeatRecords(kind) {
		names = append(names, strings.TrimSuffix(strings.TrimPrefix(filepath.Base(path), kind+"-"), ".json"))
	}
	return names
}

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
