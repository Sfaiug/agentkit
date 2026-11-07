package seat

import (
	"time"

	"agentkit/internal/run"
)

// waitStands is whether the seat file keeps a wait on the seat's usage, which watch.seat_account
// may end whatever the screen shows.
func waitStands(file *run.Object) bool { return file != nil && file.Truthy("usage_wait") }

// ownTurn is whether the seat's turn in flight began since its usage wait: one no limit refused
// is the owner's, answered by its account, so it is never continued, reopened under or typed into.
func (found sight) ownTurn(own string, waiting *run.Object) bool {
	flight, began := found.turnInFlight(own)
	turned, dated := run.Num(began)
	if !flight || !dated || waiting == nil {
		return false
	}
	from, since := run.Num(waiting.Get("since"))
	return since && turned > from
}

// waitEnds is what watch.seat_account does with a seat refused nothing, waiting on its one
// account, which has room again: the owner's own turn (ownTurn) ends the wait, nothing typed,
// and a pane redrawn meanwhile, as a working harness's spinner is every second, is no reason to
// keep it.  The returned write ends it, keeping a refusal handled; the caller holds the locks the
// look and the write take.  False, nothing written, leaves to Python a wait whose turn ak would
// continue, and one whose end gives the seat a word its ladder does not read.
func (seat Seat) waitEnds(state string, live Live, found sight, now time.Time) (func() error, bool) {
	if !found.ownTurn(seat.own, live.File.Dict("usage_wait")) {
		return nil, false
	}
	var handled any
	if live.File.Truthy("usage_refusal") {
		handled = live.File.Get("usage_refusal")
	}
	ended := []field{{"usage_wait", nil}, {"usage_refusal", handled}}
	facts := climbingOf(state, seat, found, seconds(now))
	facts.file = facts.file.Copy()
	for _, each := range ended {
		facts.file.Set(each.key, each.value)
	}
	if _, err := facts.climb(); err != nil {
		return nil, false
	}
	return func() error { return writeSeat(state, seat.Name, ended) }, true
}
