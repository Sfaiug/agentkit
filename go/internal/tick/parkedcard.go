package tick

import (
	"agentkit/internal/notify"
	"agentkit/internal/seat"
)

// cardParked sends a parked run's line its seat did not take as the seat's needs card, once for
// the step it stalled at (watch.tell_parked's notify.shaped), where a line typed would join text
// in its composer.  True once the card is accepted; a composer read empty, and a card Go does not
// evaluate, are Python's, nothing written.
func (t *ticking) cardParked(name, id, step, line string) bool {
	if !seat.Drafted(name) {
		return false
	}
	cut := []rune("stalled:" + id + ":" + step)
	carded, err := notify.NeedsAsked(name, line, string(cut[:min(len(cut), 200)]), false, seat.AskedWord, t.log.errOut)
	if carded && err == nil {
		// the question turned the seat's word, which Go's card transitions read as published
		seat.Publish(name)
	}
	return carded && err == nil
}
