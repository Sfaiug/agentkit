package seat

import (
	"time"

	"agentkit/internal/run"
)

// runParked is rung 3: a run of its own parked with no retry scheduled waits for the owner, and the
// oldest says why.  Go reads a parked error, whose line is its parked line; a seat nobody is in
// owes it at Python's rung 4, which Go does not read.
func runParked(facts climbing) (*answer, error) {
	if _, err := aRunOfItsOwn(facts); err != nil {
		return nil, err
	}
	var first *ran
	for i, each := range facts.mine {
		if each.record.Str("state") == "error" && each.view != nil && each.view.needs &&
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
	now := time.Unix(0, int64(facts.now*1e9))
	return &answer{word: "needs you", reason: run.ParkedLine(first.record, first.name, now), since: first.record.Get("finished_at")}, nil
}
