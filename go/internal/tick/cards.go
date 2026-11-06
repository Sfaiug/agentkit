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

// answerable is whether typed answers is Go's to carry for the seat (notify.answer_typed): nothing
// asked, or the owner's answers in its conversation are Go's to read.
func answerable(live seat.Live) bool {
	_, asked := notify.AskedAt(live.Name)
	return notify.Last(live.Name) == nil && !live.File.Truthy("unasked") && (!asked || notify.RetiredQuestion(live.Name)) || notify.AnswersRead(live.Name)
}

// cardsHeld is whether every card is a seat's, or one of a seat nothing is left of, which the row
// closes (notify.tick_cards).
func cardsHeld() bool {
	seats, known := seat.Seats(time.Now())
	return known && !slices.ContainsFunc(recorded("card"), func(name string) bool { return !slices.Contains(seats, name) && !seat.Unheld(name) })
}

// recorded is the seat each record of that kind is named for.
func recorded(kind string) (names []string) {
	for _, path := range config.SeatRecords(kind) {
		names = append(names, strings.TrimSuffix(strings.TrimPrefix(filepath.Base(path), kind+"-"), ".json"))
	}
	return names
}
