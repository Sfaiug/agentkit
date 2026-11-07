package tick

import (
	"agentkit/internal/notify"
	"agentkit/internal/seat"
)

// cardParked sends a parked run's line its seat did not take as the seat's needs card, once for
// the step it stalled at (watch.tell_parked's notify.shaped), where a line typed would join text
// in its composer.  True once the card is accepted; a composer read empty, and a card Go does not
// evaluate, are Python's.
func (t *ticking) cardParked(name, id, step, line string) bool {
	if !seat.Drafted(name) {
		return false
	}
	cut := []rune("stalled:" + id + ":" + step)
	source := string(cut[:min(len(cut), 200)])
	carded, err := notify.Needs(name, line, source, true, seat.Published, t.log.errOut)
	if notice := notify.Last(name); err == nil && !carded && notice != nil && notice.Str("source") == source {
		// Go cards a question on the word its seat published with it: shaped's word, the one the
		// question on record turned
		seat.Publish(name)
		carded, err = notify.Needs(name, line, source, false, seat.Published, t.log.errOut)
	}
	return carded && err == nil
}
