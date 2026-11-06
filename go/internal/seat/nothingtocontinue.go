package seat

import (
	"slices"

	"agentkit/internal/config"
	"agentkit/internal/plan"
	"agentkit/internal/run"
	usages "agentkit/internal/usage"
)

// spentAlone is whether the model's one subscription is spent as its meters last read, which
// watch.seat_account waits out for any seat on it, refused or not.  A provider listing accounts
// is MoveAccount's to move from.
func spentAlone(name string, model config.Model) bool {
	accounts, err := config.Accounts(model.Provider)
	readings, unread := usages.Cached()
	return err == nil && len(accounts) == 0 && unread == nil && readings.Spent(name) != ""
}

// mayRestDone is whether watch.done_unprompted may hold of the seat, which Go leaves to Python:
// its plan is finished, or unread, and nothing has prompted it since its last write.  The stop
// file's `turn` stamps each prompt, the line's or the owner's (watch.prompted_since), and one
// since says it does not hold, whatever else done_unprompted reads.
func mayRestDone(name string) bool {
	finished, err := plan.Finished(name)
	if err != nil || !finished {
		return err != nil
	}
	done, _ := plan.DoneAt(name)
	turn := 0.0
	if stop, _ := run.ReadJSON(ownFile("stop", name)); stop != nil {
		turn, _ = stop.Num("turn")
	}
	return done.IsZero() || turn <= seconds(done)
}

// keepsOwnWord is whether a wait on the seat's usage leaves it its own word (watch._session_state):
// one until its windows come back that no limit cut a turn off for, its work done and live
// (watch.work_live: its plan finished, and no run of its own owing work or awaiting its live
// check), and no line or news owed it.  The owner, 2 Nov 2026: "Out of usage should be when there
// is no more usage from the provider to continue."  News keeps the wait standing only once a look
// has read the screen, and the look writes what it read: before it, a wait news would keep
// standing is Python's, as nothing yet says whether it stands.
func keepsOwnWord(facts climbing, wait *run.Object) (bool, error) {
	finished, err := plan.Finished(facts.name)
	if !wait.Truthy("until") || wait.Truthy("continue") || err != nil || !finished ||
		slices.ContainsFunc(facts.file.List("owed_lines"), func(line any) bool {
			owed, ok := line.(*run.Object)
			return !ok || !owed.Truthy("switch")
		}) {
		return false, nil
	}
	owes, err := facts.runsOwe()
	live := slices.ContainsFunc(facts.mine, func(each ran) bool { return each.view != nil && each.view.live })
	switch {
	case owes || live || err != nil:
		return false, err
	case facts.news() == "":
		return true, nil
	case facts.found.authority == "":
		return false, ErrUnread
	}
	return false, nil
}
