package loop

import (
	"fmt"
	"path/filepath"
	"slices"

	"agentkit/internal/pick"
	"agentkit/internal/run"
	"agentkit/internal/usage"
)

// asIs is whether the resume's pick keeps the saved pair.
func asIs(dir string, record *run.Object, rules *pick.Rules, room ready) bool {
	executor, reviewer, _ := resumeModels(record, rules, room)
	return executor == record.Str("executor") && reviewer == record.Str("reviewer") && !selfReviewYields(dir, record, rules, room)
}

// picking is what a resume's pick reads of a run: the lists it was launched with, and the meters
// and harnesses as they stand.  A dry tick's pick probes nothing, as Python's (watch.local_passes):
// it reads the usage snapshot as it stands, where a read of it is Go's, and asks no harness.
func picking(record *run.Object, dry bool) (*pick.Rules, ready, bool) {
	l := &loop{workers: names(record.List("workers")), reviewers: names(record.List("reviewers"))}
	rules, ok := l.rules()
	if dry {
		readings, err := usage.Cached()
		return rules, ready{Readings: readings}, ok && err == nil && usage.Check() == nil
	}
	readings, err := usage.Read()
	if !ok || err != nil {
		return nil, ready{}, false
	}
	return rules, ready{readings, unable()}, true
}

// resumeModels is the pair a resume goes on with, Python's staffing.resume_models: the saved
// executor while it can run, with the saved reviewer while that has room, else its best; else the
// best pair with room, a handover; else why none can run yet, each spent window named.  All ""
// where the saved executor cannot run here and no pair forms, an error Python's resume raises.
func resumeModels(record *run.Object, rules *pick.Rules, room ready) (executor, reviewer, dry string) {
	executor, reviewer = record.Str("executor"), record.Str("reviewer")
	if executor != "" && room.Spent(executor) == "" {
		if slices.Contains(rules.Order(room, true, nil), reviewer) {
			return executor, reviewer, ""
		}
		if reviewer, found := rules.PairFor(room, executor); found {
			return executor, reviewer, ""
		}
		return "", "", "no eligible reviewer: no worker with budget is left to review for executor " + executor + "; waiting for review"
	}
	if executor, reviewer, found := rules.Pair(room); found {
		return executor, reviewer, ""
	}
	if room.cannot[executor] != "" {
		return "", "", ""
	}
	return "", "", rules.Dry(room.Readings.Spent)
}

// selfReviewYields is whether a saved self-review steps aside for a pair that is none, Python's
// resume_run: once the round's work is answered only the reviewer may change, so the executor
// keeps it; before, any pair with room may take it.
func selfReviewYields(dir string, record *run.Object, rules *pick.Rules, room ready) bool {
	executor := record.Str("executor")
	if !rules.Same(executor, record.Str("reviewer")) {
		return false
	}
	round := filepath.Join(dir, fmt.Sprintf("round-%d", len(record.List("round_summaries"))+1))
	finished := func(name string) bool {
		latest := lastAttempt(round, name)
		return latest != "" && exists(filepath.Join(latest, "final.md"))
	}
	next, other, found := rules.Pair(room)
	if record.Truthy("review_pending") || finished("executor") || finished("fixer") {
		next = executor
		other, found = rules.PairFor(room, executor)
	}
	return found && !rules.Same(next, other)
}
