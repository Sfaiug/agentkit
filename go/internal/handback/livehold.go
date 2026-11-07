package handback

import (
	"time"

	"agentkit/internal/config"
	"agentkit/internal/harness"
	"agentkit/internal/plan"
	"agentkit/internal/run"
	"agentkit/internal/seat"
)

// heldForLive is Python's merge_waits_for_live: a merge awaiting its live check holds its ending,
// to say both in one line, unless its seat owes a line none of its other going runs
// serves, or another such run is going and the seat's `ak wait` names something else. A line
// already in the composer keeps its Enter.
func heldForLive(record *run.Object) (bool, error) {
	if record.Truthy("handback_typed") || !seat.AwaitingLive(record, time.Now()) {
		return false, nil
	}
	served, err := othersGoing(record)
	if err != nil || served == nil {
		return err == nil, err
	}
	if unserved, err := plan.Unserved(run.Seat(record), served); unserved || err != nil {
		return false, err
	}
	return seat.WaitNames(run.Seat(record), record)
}

// liveEnding is how a delivery's ending meets its change going live, as Python's announce and
// hand_back decide it: held until it does (merge_waits_for_live), or saying in its one line that
// it did (carries_live).  An error where Go cannot read what decides it as Python does.
func liveEnding(record *run.Object) (held, live bool, err error) {
	if held, err = heldForLive(record); held || err != nil || !record.Truthy("live_at") {
		return held, false, err
	}
	live, err = carries(record)
	return false, live, err
}

// carries is Python's carries_live, live_at aside, for a merge passing its live check now too: its
// ending is owed, its seat still has to hear it went live (live_owed), and no live notice waits in
// a composer but in the ending's own line.
func carries(record *run.Object) (bool, error) {
	if !run.OwesEnding(record, time.Now()) || !record.Truthy("merged") || record.Truthy("live_notified") ||
		!run.Equal(record.Get("live_typed"), record.Get("handback_typed")) {
		return false, nil
	}
	session := run.Seat(record)
	if session == "" {
		return false, nil // a seat owes nothing (seat_owes_nothing): the notice is recorded
	}
	if owes, err := plan.Owes(session); !owes || err != nil {
		return false, err
	}
	if harness.TakesContext(config.SeatHarness(session)) {
		return true, nil // where it ends no wait, it rides on the seat's next prompt
	}
	return seat.EndsWait(session, nil, record)
}

// othersGoing is the plan line each other going run of the record's seat serves, "" for none; nil
// where none is going.
func othersGoing(record *run.Object) ([]string, error) {
	records, err := run.Records()
	if err != nil {
		return nil, err
	}
	seatOf, session, now := run.Seats(), run.Seat(record), time.Now()
	var served []string
	for _, other := range records {
		if seatOf(other) != session || run.Equal(other.Get("run_id"), record.Get("run_id")) {
			continue
		}
		if run.Going(other, now) {
			served = append(served, other.Str("plan_line"))
		}
	}
	return served, nil
}
