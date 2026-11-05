package tick

import (
	"path/filepath"
	"slices"
	"strings"
	"time"

	"agentkit/internal/config"
	"agentkit/internal/notify"
	"agentkit/internal/seat"
)

// unasked is whether typed answers has nothing to do: nothing asked, or a recorded question
// with no newer message from the owner (notify.answer_typed).
func unasked(live seat.Live) bool {
	_, asked := notify.AskedAt(live.Name)
	return notify.Last(live.Name) == nil && !live.File.Truthy("unasked") && (!asked || notify.RetiredQuestion(live.Name)) || unansweredQuestion(live) || notify.UnansweredDialog(live.Name) || notify.UnansweredNeed(live.Name)
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
