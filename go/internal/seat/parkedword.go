package seat

import (
	"cmp"
	"strings"
	"time"

	"agentkit/internal/config"
	"agentkit/internal/plan"
	"agentkit/internal/run"
)

// parked is whether nothing but the owner moves the run (watch.parked_runs): an error still the
// owner's, a stalled run undecided, or a merge wait only its age turned away.
func parked(record *run.Object, view runView, index run.Index, now time.Time) bool {
	switch record.Str("state") {
	case "error":
		return view.needs
	case "stalled":
		return view.undecided
	case "waiting":
		ended := record.Copy()
		ended.Set("finished_at", seconds(now))
		return !view.going && run.TickAdmission(ended, now) != "" && !index.MergedOver(record)
	}
	return false
}

// resumes is whether the run moves on by itself (watch.resumes_itself): `going` counts a stalled
// run, but only `ak run resume` moves one.
func (each ran) resumes() bool {
	return each.going() && each.record.Str("state") != "stalled"
}

// runParked is rung 3: a run of its own parked waits for the owner, and the oldest says why.  A
// seat nobody is in owes it at Python's rung 4, which Go does not read.
func runParked(facts climbing) (*answer, error) {
	if _, err := aRunOfItsOwn(facts); err != nil {
		return nil, err
	}
	var first *ran
	for i, each := range facts.mine {
		if each.view != nil && each.view.parked &&
			(first == nil || run.FirstNumber(each.record, "finished_at") < run.FirstNumber(first.record, "finished_at")) {
			first = &facts.mine[i]
		}
	}
	switch {
	case first == nil:
		return nil, nil
	case facts.gone != nil:
		return nil, ErrUnread
	}
	var reason string
	switch first.record.Str("state") {
	case "stalled":
		// from its id, never its error: a long step cuts the command in that one short
		reason = "run " + first.name + " stalled: resume it with `ak run resume " + first.name + "`"
	case "waiting":
		reason = "run " + first.name + " waits to merge: " + parkedReason(first.record)
	default:
		reason = run.ParkedLine(first.record, first.name, time.Unix(0, int64(facts.now*1e9)))
	}
	return &answer{word: "needs you", reason: reason, since: first.record.Get("finished_at")}, nil
}

// runUndecided: a plan whose every line is proven is not done while a run of its own sits
// undecided, as the stop hook's third stop stands on it.  A seat nobody is in owes it at Python's
// rung 4, and a FAIL's reason is its rounds and findings, neither of which Go reads here.
func runUndecided(facts climbing) (*answer, error) {
	if finished, err := plan.Finished(facts.name); err != nil || !finished {
		return nil, nil // planFinished reads the plan Go cannot
	}
	for _, each := range facts.mine {
		if each.view == nil || !each.view.undecided {
			continue
		}
		reason := parkedReason(each.record)
		if facts.gone != nil || reason == "" {
			return nil, ErrUnread
		}
		return &answer{word: "needs you", reason: "run " + each.name + " parked: " + reason, since: facts.found.began}, nil
	}
	return nil, nil
}

// parkedReason is why a parked run stopped, in its own words, cut as its hand-back cuts them
// (handback.handback_reason); "" for an ending's.
func parkedReason(record *run.Object) string {
	said, state := config.Fold(record.Str("error")), record.Str("state")
	switch {
	case state == "error" || state == "waiting":
		said = config.Fold(cmp.Or(record.Str("error"), "no reason was recorded"))
	case strings.HasPrefix(said, "killed: memory cap"):
	case !run.Ended(record) && run.NeedsRecovery(record):
		said = strings.TrimRight(config.Fold(run.RecoveryReason(record)), ".")
	default:
		return ""
	}
	cut := []rune(said)
	return string(cut[:min(len(cut), 300)])
}
