package cli

import (
	"errors"
	"slices"
	"time"

	"agentkit/internal/job"
	"agentkit/internal/plan"
	"agentkit/internal/run"
	"agentkit/internal/seat"
)

// errExhausted is a run of the seat's whose wait transitions.exhausted_wait reads, not Go yet.
var errExhausted = errors.New("an exhausted run, which Python's exhausted_wait reads")

// recordedEnding is stop.recorded_ending as the stop hook asks it: whether what the seat recorded
// lets its turn end, and whether runs of its own sit parked undecided, which hold it.  A question
// ends it past everything; an unnamed seat's name holds everything else, and a parked run a plan
// owing nothing and every wait.  A run of its own going, merged and awaiting its live check, or
// started since the turn began, a job it can wait on and its own `ak wait` let it end.
func recordedEnding(name string, record map[string]any, asked bool, since float64) (ends, parked bool, err error) {
	now := time.Now()
	switch {
	case asked:
		return true, false, nil
	case record["unnamed"] == true:
		return false, false, nil
	}
	if parked, err := run.Parked(name, now); parked || err != nil {
		return false, parked, err
	}
	if owes, err := plan.Owes(name); !owes || err != nil {
		return !owes, false, err
	}
	for _, dir := range run.Dirs() {
		mine, _ := run.Read(dir)
		if mine == nil || run.Seat(mine) != name {
			continue
		}
		if mine.Str("state") == "exhausted" {
			return false, false, errExhausted
		}
		if run.Going(mine, now) || seat.AwaitingLive(mine, now) || startedSince(mine, since) {
			return true, false, nil
		}
	}
	return job.Waiting(name) || seat.Waiting(name), false, nil
}

// startedSince is whether the run was started or queued in this turn and has not stopped on an
// error or a wait since: the prompt hook's wait on work launched in the turn holds past its end.
func startedSince(mine *run.Object, since float64) bool {
	if slices.Contains([]string{"error", "waiting"}, mine.Str("state")) {
		return false
	}
	for _, key := range []string{"started_at", "queued_at"} {
		if at, dated := mine.Num(key); dated && at >= since {
			return true
		}
	}
	return false
}
