package tick

import (
	"path/filepath"
	"slices"
	"strings"

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
func (t *ticking) cardsHeld() bool {
	lives, _ := t.seats()
	return !slices.ContainsFunc(config.SeatRecords("card"), func(path string) bool {
		name := strings.TrimSuffix(strings.TrimPrefix(filepath.Base(path), "card-"), ".json")
		return !slices.ContainsFunc(lives, func(live seat.Live) bool { return live.Name == name })
	})
}

// uncarded is whether neither the seat's word nor its card is one a card goes out for.
func uncarded(live seat.Live) bool {
	carded := notify.CardWord(live.Name)
	return !slices.Contains([]string{"needs you", "done"}, live.Word) && carded != "needs you" && carded != "done"
}

// cards is the card transitions row where no seat reads `needs you` or `done`: each seat's card
// follows the word its health look published.
func (t *ticking) cards() error {
	lives, _ := t.seats()
	for _, live := range lives {
		if err := notify.Turned(live.Name, seat.Published); err != nil {
			return err
		}
	}
	return nil
}
