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
// no limit cut a turn off for it, its work is done and live, and no line is owed it.  The owner,
// 2 Nov 2026: "Out of usage should be when there is no more usage from the provider to continue."
// Its runs, which work_live and news_owed read too, and its `ak wait` are none where this is read.
func keepsOwnWord(name string, file, wait *run.Object) bool {
	finished, err := plan.Finished(name)
	return !wait.Truthy("continue") && err == nil && finished &&
		!slices.ContainsFunc(file.List("owed_lines"), func(line any) bool {
			owed, ok := line.(*run.Object)
			return !ok || !owed.Truthy("switch")
		})
}
