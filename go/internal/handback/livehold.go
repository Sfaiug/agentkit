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
// to say both in one line (CarriesLive), unless its seat owes a line none of its other going runs
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

// CarriesLive is Python's carries_live: the run's ending, still to be said, says in its one line
// that its change went live after it.
func CarriesLive(record *run.Object) (bool, error) {
	if !record.Truthy("live_at") {
		return false, nil
	}
	return carries(record)
}

// carries is CarriesLive for a merge passing its live check now, before live_at is written: its
// ending is owed, its seat still has to hear it went live (Python's live_owed), and no live
// notice waits in a composer but in the ending's own line.
func carries(record *run.Object) (bool, error) {
	if !run.OwesEnding(record, time.Now()) || !record.Truthy("merged") || record.Truthy("live_notified") ||
		!run.Equal(record.Get("live_typed"), record.Get("handback_typed")) {
		return false, nil
	}
	session := run.Seat(record)
	if owes, err := plan.Owes(session); !owes || err != nil {
		return false, err
	}
	if harness.TakesContext(config.SeatHarness(session)) {
		return true, nil // where it ends no wait, it rides on the seat's next prompt
	}
	return endsWait(record)
}

// endsWait is Python's ends_wait: the seat's `ak wait` names this run or its pull request, no other
// run of the seat is going, or the seat owes a line none of them serves.
func endsWait(record *run.Object) (bool, error) {
	if named, err := seat.WaitNames(run.Seat(record), record); named || err != nil {
		return named, err
	}
	served, err := othersGoing(record)
	if err != nil || served == nil {
		return err == nil, err
	}
	return plan.Unserved(run.Seat(record), served)
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
