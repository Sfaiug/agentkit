package seat

import (
	"os"
	"slices"
	"time"

	"agentkit/internal/config"
	"agentkit/internal/job"
	"agentkit/internal/plan"
	"agentkit/internal/run"
)

// RecordedEnding is stop.recorded_ending: whether what the seat recorded
// lets its turn end, and whether runs of its own sit parked undecided, which hold it.  A question
// ends it past everything; an unnamed seat's name holds everything else, and a parked run a plan
// owing nothing and every wait.  A run of its own going, merged and awaiting its live check, or
// started since the turn began, a job it can wait on and its own `ak wait` let it end.  From every
// run's record as its caller read them, or with none as they stand (stop._ending_work).
func RecordedEnding(name string, census []*run.Object, record map[string]any, asked bool, since ...float64) (ends, parked bool, err error) {
	now := time.Now()
	switch {
	case asked:
		return true, false, nil
	case record["unnamed"] == true:
		return false, false, nil
	}
	if census == nil {
		if census, err = run.Records(); err != nil {
			return false, false, err
		}
	}
	if run.Parked(name, census, now) {
		return false, true, nil
	}
	if owes, err := plan.Owes(name); !owes || err != nil {
		return !owes, false, err
	}
	seat := run.Seats()
	for _, mine := range census {
		if seat(mine) != name {
			continue
		}
		if run.Going(mine, now) || AwaitingLive(mine, now) || len(since) > 0 && startedSince(mine, since[0]) {
			return true, false, nil
		}
	}
	return job.Waiting(name) || Waiting(name), false, nil
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

// EndsWait is whether this ending ends the explicit wait its seat named, or leaves
// nothing recorded to let the seat's turn end while its plan still owes work.
func EndsWait(name string, census []*run.Object, ending *run.Object) (bool, error) {
	if named, err := WaitNames(name, ending); named || err != nil {
		return named, err
	}
	_, record, err := config.ResolveSession(name)
	if err != nil {
		return false, err
	}
	ends, _, err := RecordedEnding(name, census, record, false)
	return !ends, err
}

// WaitNames is whether the seat's `ak wait`, not yet told, names this ending's run or pull request.
func WaitNames(name string, ending *run.Object) (bool, error) {
	file, err := run.ReadJSON(seatFile(name))
	if err != nil && !os.IsNotExist(err) {
		return false, err
	}
	if file != nil {
		if wait := file.Dict("wait"); wait != nil && !wait.Truthy("told") {
			id, pr := ending.Str("run_id"), ending.Str("pr")
			return id != "" && (id == wait.Str("on") || id == wait.Str("run")) || pr != "" && pr == wait.Str("on"), nil
		}
	}
	return false, nil
}
