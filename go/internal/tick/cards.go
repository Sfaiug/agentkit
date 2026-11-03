package tick

import (
	"cmp"
	"path/filepath"
	"slices"
	"strings"
	"time"

	"agentkit/internal/config"
	"agentkit/internal/notify"
	"agentkit/internal/seat"
)

// unasked is whether nothing the seat asked waits on the owner's answer in its conversation: no
// notice standing, no question kept back, and no `needs you` its card holds (notify.answer_typed).
func unasked(live seat.Live) bool {
	_, asked := notify.AskedAt(live.Name)
	return notify.Last(live.Name) == nil && !live.File.Truthy("unasked") && !asked
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
// health row published, read under the card's lock and never off the screen again; the first seat
// whose card or word is one a card goes out for ends the tick there.
func cards() error {
	names, known := seat.Seats(time.Now())
	if !known {
		return errLeft
	}
	for _, name := range names {
		if carried, err := notify.Turned(name, seat.Published); err != nil || !carried {
			return cmp.Or(err, errLeft)
		}
	}
	return nil
}
