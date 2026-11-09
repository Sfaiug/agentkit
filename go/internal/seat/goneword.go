package seat

import (
	"time"

	"agentkit/internal/harness"
	"agentkit/internal/plan"
	"agentkit/internal/run"
)

func conversationOwned(reader harness.Reader, record *run.Object) bool {
	if resumable, known := reader.Resumable(record); known {
		return resumable
	}
	owned, _ := reader.Owns(record, record.Str("conversation"))
	return record.Str("conversation") != "" && (record.Str("id_source") == "launcher" || owned)
}

// reconciled drops a conversation the harness does not own, as Python's plugin.reconcile does.
func (seat Seat) reconciled(fields []field) func(*run.Object) bool {
	return func(record *run.Object) bool {
		changes := fields
		if seat.unowned && record.Truthy("conversation") && !conversationOwned(seat.reader, record) {
			changes = append(changes, field{"conversation", nil}, field{"resumable", false})
		}
		return set(changes)(record)
	}
}

// goneAt climbs the same ladder without a screen; its place comes from orch's ordered rows.
func (seat *Seat) goneAt(state string, place int, now time.Time) error {
	facts := climbingOf(state, *seat, sight{}, seconds(now))
	facts.gone, facts.place = seat, place
	said, err := facts.climb()
	if err == nil {
		seat.Word, seat.reason, seat.since, seat.question, seat.anew, seat.login = said.word, said.reason, said.since, said.question, said.anew, said.login
	}
	return err
}

// goneRuns reads the runs the home's reader vetted, including Menu's snapshots for live seats.
func goneRuns(facts climbing) (*answer, error) {
	if _, err := aRunOfItsOwn(facts); err != nil {
		return nil, err
	}
	var going []ran
	for _, each := range facts.mine {
		if each.resumes() {
			going = append(going, each)
		}
	}
	if len(going) == 0 {
		return nil, nil
	}
	reason, since := working(going)
	return &answer{word: "working", reason: reason, since: since}, nil
}

// nobodyIn is rung 4: an owner-closed seat rests; another needs reopening while work is owed,
// the done check its finished plan owes aside (watch.owes_work), for which it rests.  A finished
// plan passes on to the shared alert and plan rungs, except asleep, whose way back stays beside
// its word.
func nobodyIn(facts climbing) (*answer, error) {
	if facts.gone == nil {
		return nil, nil
	}
	reason := facts.gone.closedReason(facts.place)
	if facts.gone.closed {
		return &answer{word: "idle", reason: reason}, nil
	}
	owed, err := plan.OwesLine(facts.name)
	if err != nil {
		return nil, ErrUnread
	}
	if owed || facts.notice != nil {
		return &answer{word: "needs you", reason: reason}, nil
	}
	finished, err := plan.Finished(facts.name)
	if err != nil {
		return nil, ErrUnread
	}
	if !finished {
		return &answer{word: "idle", reason: reason}, nil
	}
	if facts.gone.asleep {
		return &answer{word: "done", reason: reason}, nil
	}
	return nil, nil
}
